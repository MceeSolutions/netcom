# -*- coding: utf-8 -*-

import base64
import logging
import psycopg2
import smtplib

from email.utils import formataddr
from odoo import _, api, exceptions, fields, models, tools
from odoo.tools import pycompat, ustr
from odoo.addons.base.ir.ir_mail_server import MailDeliveryException
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)



class MailMail(models.Model):
    _inherit = 'mail.mail'

    recipient_cc_ids = fields.Many2many(
        'res.partner', 'mail_mail_cc_res_partner_rel',
        'mail_mail_id', 'partner_id', 'CC (Partners)')

    recipient_bcc_ids = fields.Many2many(
        'res.partner', 'mail_mail_bcc_res_partner_rel',
        'mail_mail_id', 'partner_id', 'BCC (Partners)')

    @api.multi
    def _send(self, auto_commit=False, raise_exception=False, smtp_session=None):
        IrMailServer = self.env['ir.mail_server']
        for mail_id in self.ids:
            try:
                mail = self.browse(mail_id)
                if mail.state != 'outgoing':
                    if mail.state != 'exception' and mail.auto_delete:
                        mail.sudo().unlink()
                    continue
                # TDE note: remove me when model_id field is present on mail.message - done here to avoid doing it multiple times in the sub method
                if mail.model:
                    model = self.env['ir.model']._get(mail.model)[0]
                else:
                    model = None
                if model:
                    mail = mail.with_context(model_name=model.name)

                # load attachment binary data with a separate read(), as prefetching all
                # `datas` (binary field) could bloat the browse cache, triggerring
                # soft/hard mem limits with temporary data.
                attachments = [(a['datas_fname'], base64.b64decode(a['datas']), a['mimetype'])
                               for a in mail.attachment_ids.sudo().read(['datas_fname', 'datas', 'mimetype'])]

                # specific behavior to customize the send email for notified partners
                email_list = []
                if mail.email_to:
                    email_list.append(mail.send_get_email_dict())
                for partner in mail.recipient_ids:
                    email_list.append(mail.send_get_email_dict(partner=partner))

                if mail.cc_visible:
                    email_cc_list = []
                    for partner_cc in mail.recipient_cc_ids:
                        email_to = formataddr((partner_cc.name or 'False', partner_cc.email or 'False'))
                        email_cc_list.append(email_to)
                    # Convert Email List To String For BCC & CC
                    email_cc_string = ','.join(email_cc_list)
                else:
                    email_cc_string = ''

                if mail.bcc_visible:
                    email_bcc_list = []
                    for partner_bcc in mail.recipient_bcc_ids:
                        email_to = formataddr((partner_bcc.name or 'False', partner_bcc.email or 'False'))
                        email_bcc_list.append(email_to)
                    # Convert Email List To String For BCC & CC
                    email_bcc_string = ','.join(email_bcc_list)
                else:
                    email_bcc_string = ''

                # headers
                headers = {}
                ICP = self.env['ir.config_parameter'].sudo()
                bounce_alias = ICP.get_param("mail.bounce.alias")
                catchall_domain = ICP.get_param("mail.catchall.domain")
                if bounce_alias and catchall_domain:
                    if mail.model and mail.res_id:
                        headers['Return-Path'] = '%s+%d-%s-%d@%s' % (bounce_alias, mail.id, mail.model, mail.res_id, catchall_domain)
                    else:
                        headers['Return-Path'] = '%s+%d@%s' % (bounce_alias, mail.id, catchall_domain)
                if mail.headers:
                    try:
                        headers.update(safe_eval(mail.headers))
                    except Exception:
                        pass

                # Writing on the mail object may fail (e.g. lock on user) which
                # would trigger a rollback *after* actually sending the email.
                # To avoid sending twice the same email, provoke the failure earlier
                mail.write({
                    'state': 'exception',
                    'failure_reason': _('Error without exception. Probably due do sending an email without computed recipients.'),
                })
                mail_sent = False

                # Update notification in a transient exception state to avoid concurrent
                # update in case an email bounces while sending all emails related to current
                # mail record.
                notifs = self.env['mail.notification'].search([
                    ('is_email', '=', True),
                    ('mail_message_id', 'in', mail.mapped('mail_message_id').ids),
                    ('res_partner_id', 'in', mail.mapped('recipient_ids').ids),
                    ('email_status', 'not in', ('sent', 'canceled'))
                ])
                if notifs:
                    notifs.sudo().write({
                        'email_status': 'exception',
                    })

                # build an RFC2822 email.message.Message object and send it without queuing
                res = None
                for email in email_list:
                    msg = IrMailServer.build_email(
                        email_from=mail.email_from,
                        email_to=email.get('email_to'),
                        subject=mail.subject,
                        body=email.get('body'),
                        body_alternative=email.get('body_alternative'),
                        email_cc=tools.email_split_and_format(email_cc_string),
                        email_bcc=tools.email_split_and_format(email_bcc_string),
                        reply_to=mail.reply_to,
                        attachments=attachments,
                        message_id=mail.message_id,
                        references=mail.references,
                        object_id=mail.res_id and ('%s-%s' % (mail.res_id, mail.model)),
                        subtype='html',
                        subtype_alternative='plain',
                        headers=headers)
                    try:
                        res = IrMailServer.send_email(
                            msg, mail_server_id=mail.mail_server_id.id, smtp_session=smtp_session)
                    except AssertionError as error:
                        if str(error) == IrMailServer.NO_VALID_RECIPIENT:
                            # No valid recipient found for this particular
                            # mail item -> ignore error to avoid blocking
                            # delivery to next recipients, if any. If this is
                            # the only recipient, the mail will show as failed.
                            _logger.info("Ignoring invalid recipients for mail.mail %s: %s",
                                         mail.message_id, email.get('email_to'))
                        else:
                            raise
                if res:
                    mail.write({'state': 'sent', 'message_id': res, 'failure_reason': False})
                    mail_sent = True

                # /!\ can't use mail.state here, as mail.refresh() will cause an error
                # see revid:odo@openerp.com-20120622152536-42b2s28lvdv3odyr in 6.1
                if mail_sent:
                    _logger.info('Mail with ID %r and Message-Id %r successfully sent', mail.id, mail.message_id)
                mail._postprocess_sent_message(mail_sent=mail_sent)
            except MemoryError:
                # prevent catching transient MemoryErrors, bubble up to notify user or abort cron job
                # instead of marking the mail as failed
                _logger.exception(
                    'MemoryError while processing mail with ID %r and Msg-Id %r. Consider raising the --limit-memory-hard startup option',
                    mail.id, mail.message_id)
                raise
            except (psycopg2.Error, smtplib.SMTPServerDisconnected):
                # If an error with the database or SMTP session occurs, chances are that the cursor
                # or SMTP session are unusable, causing further errors when trying to save the state.
                _logger.exception(
                    'Exception while processing mail with ID %r and Msg-Id %r.',
                    mail.id, mail.message_id)
                raise
            except Exception as e:
                failure_reason = tools.ustr(e)
                _logger.exception('failed sending mail (id: %s) due to %s', mail.id, failure_reason)
                mail.write({'state': 'exception', 'failure_reason': failure_reason})
                mail._postprocess_sent_message(mail_sent=False)
                if raise_exception:
                    if isinstance(e, AssertionError):
                        # get the args of the original error, wrap into a value and throw a MailDeliveryException
                        # that is an except_orm, with name and value as arguments
                        value = '. '.join(e.args)
                        raise MailDeliveryException(_("Mail Delivery Failed"), value)
                    raise

            if auto_commit is True:
                self._cr.commit()
        return True


class Message(models.Model):
    _inherit = 'mail.message'

    partner_cc_ids = fields.Many2many(
        'res.partner', 'mail_message_cc_res_partner_rel',
        'message_id', 'partner_id', 'CC (Recipients)')

    partner_bcc_ids = fields.Many2many(
        'res.partner', 'mail_message_bcc_res_partner_rel',
        'message_id', 'partner_id', 'BCC (Recipients)')

    cc_visible = fields.Boolean('CC Visible')
    bcc_visible = fields.Boolean('BCC Visible')

class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    @api.multi
    @api.returns('self', lambda value: value.id)
    def message_post(self, body='', subject=None, message_type='notification',
                     subtype=None, parent_id=False, attachments=None,
                     content_subtype='html', **kwargs):
        """ Post a new message in an existing thread, returning the new
            mail.message ID.
            :param int thread_id: thread ID to post into, or list with one ID;
                if False/0, mail.message model will also be set as False
            :param str body: body of the message, usually raw HTML that will
                be sanitized
            :param str type: see mail_message.message_type field
            :param str content_subtype:: if plaintext: convert body into html
            :param int parent_id: handle reply to a previous message by adding the
                parent partners to the message in case of private discussion
            :param tuple(str,str) attachments or list id: list of attachment tuples in the form
                ``(name,content)``, where content is NOT base64 encoded
            Extra keyword arguments will be used as default column values for the
            new mail.message record. Special cases:
                - attachment_ids: supposed not attached to any document; attach them
                    to the related document. Should only be set by Chatter.
            :return int: ID of newly created mail.message
        """
        if attachments is None:
            attachments = {}
        if self.ids and not self.ensure_one():
            raise exceptions.Warning(_('Invalid record set: should be called as model (without records) or on single-record recordset'))

        # if we're processing a message directly coming from the gateway, the destination model was
        # set in the context.
        model = False
        if self.ids:
            self.ensure_one()
            model = self._context.get('thread_model', False) if self._name == 'mail.thread' else self._name
            if model and model != self._name and hasattr(self.env[model], 'message_post'):
                RecordModel = self.env[model].with_context(thread_model=None)  # TDE: was removing the key ?
                return RecordModel.browse(self.ids).message_post(
                    body=body, subject=subject, message_type=message_type,
                    subtype=subtype, parent_id=parent_id, attachments=attachments,
                    content_subtype=content_subtype, **kwargs)

        # 0: Find the message's author, because we need it for private discussion
        author_id = kwargs.get('author_id')
        if author_id is None:  # keep False values
            author_id = self.env['mail.message']._get_default_author().id

        # 1: Handle content subtype: if plaintext, converto into HTML
        if content_subtype == 'plaintext':
            body = tools.plaintext2html(body)

        # 2: Private message: add recipients (recipients and author of parent message) - current author
        #   + legacy-code management (! we manage only 4 and 6 commands)
        partner_ids = set()
        kwargs_partner_ids = kwargs.pop('partner_ids', [])
        for partner_id in kwargs_partner_ids:
            if isinstance(partner_id, (list, tuple)) and partner_id[0] == 4 and len(partner_id) == 2:
                partner_ids.add(partner_id[1])
            if isinstance(partner_id, (list, tuple)) and partner_id[0] == 6 and len(partner_id) == 3:
                partner_ids |= set(partner_id[2])
            elif isinstance(partner_id, pycompat.integer_types):
                partner_ids.add(partner_id)
            else:
                pass  # we do not manage anything else
        if parent_id and not model:
            parent_message = self.env['mail.message'].browse(parent_id)
            private_followers = set([partner.id for partner in parent_message.partner_ids])
            if parent_message.author_id:
                private_followers.add(parent_message.author_id.id)
            private_followers -= set([author_id])
            partner_ids |= private_followers

        # 4: mail.message.subtype
        subtype_id = kwargs.get('subtype_id', False)
        if not subtype_id:
            subtype = subtype or 'mt_note'
            if '.' not in subtype:
                subtype = 'mail.%s' % subtype
            subtype_id = self.env['ir.model.data'].xmlid_to_res_id(subtype)

        # automatically subscribe recipients if asked to
        if self._context.get('mail_post_autofollow') and self.ids and partner_ids:
            partner_to_subscribe = partner_ids
            if self._context.get('mail_post_autofollow_partner_ids'):
                partner_to_subscribe = [p for p in partner_ids if p in self._context.get('mail_post_autofollow_partner_ids')]
            self.message_subscribe(list(partner_to_subscribe), force=False)

        # _mail_flat_thread: automatically set free messages to the first posted message
        MailMessage = self.env['mail.message']
        if self._mail_flat_thread and model and not parent_id and self.ids:
            messages = MailMessage.search(['&', ('res_id', '=', self.ids[0]), ('model', '=', model), ('message_type', '=', 'email')], order="id ASC", limit=1)
            if not messages:
                messages = MailMessage.search(['&', ('res_id', '=', self.ids[0]), ('model', '=', model)], order="id ASC", limit=1)
            parent_id = messages and messages[0].id or False
        # we want to set a parent: force to set the parent_id to the oldest ancestor, to avoid having more than 1 level of thread
        elif parent_id:
            messages = MailMessage.sudo().search([('id', '=', parent_id), ('parent_id', '!=', False)], limit=1)
            # avoid loops when finding ancestors
            processed_list = []
            if messages:
                message = messages[0]
                while (message.parent_id and message.parent_id.id not in processed_list):
                    processed_list.append(message.parent_id.id)
                    message = message.parent_id
                parent_id = message.id

        values = kwargs
        # Added CC AND BCC In Mail Message
        partner_cc_ids = set()
        kwargs_partner_cc_ids = kwargs.pop('partner_cc_ids', [])
        for partner_id in kwargs_partner_cc_ids:
            partner_cc_ids.add(partner_id)

        partner_bcc_ids = set()
        kwargs_partner_bcc_ids = kwargs.pop('partner_bcc_ids', [])
        for partner_id in kwargs_partner_bcc_ids:
            partner_bcc_ids.add(partner_id)

        cc_visible = kwargs.get('cc_visible')
        bcc_visible = kwargs.get('bcc_visible')
        if cc_visible:
            values.update({
                'partner_cc_ids': [(4, pccid) for pccid in partner_cc_ids],
            })
        else:
            values.update({
                'partner_cc_ids': [],
            })
        if bcc_visible:
            values.update({
                'partner_bcc_ids': [(4, pbccid) for pbccid in partner_bcc_ids],
            })
        else:
            values.update({
                'partner_bcc_ids': [],
            })

        values.update({
            'author_id': author_id,
            'model': model,
            'res_id': model and self.ids[0] or False,
            'body': body,
            'subject': subject or False,
            'message_type': message_type,
            'parent_id': parent_id,
            'subtype_id': subtype_id,
            'partner_ids': [(4, pid) for pid in partner_ids],
            'cc_visible': cc_visible,
            'bcc_visible': bcc_visible,
        })

        # 3. Attachments
        #   - HACK TDE FIXME: Chatter: attachments linked to the document (not done JS-side), load the message
        attachment_ids = self._message_post_process_attachments(attachments, kwargs.pop('attachment_ids', []), values)
        values['attachment_ids'] = attachment_ids

        # Avoid warnings about non-existing fields
        for x in ('from', 'to', 'cc'):
            values.pop(x, None)

        # Post the message
        new_message = MailMessage.create(values)



        # Post-process: subscribe author, update message_last_post
        # Note: the message_last_post mechanism is no longer used.  This
        # will be removed in a later version.
        if (self._context.get('mail_save_message_last_post') and
                model and model != 'mail.thread' and self.ids and subtype_id):
            subtype_rec = self.env['mail.message.subtype'].sudo().browse(subtype_id)
            if not subtype_rec.internal:
                # done with SUPERUSER_ID, because on some models users can post only with read access, not necessarily write access
                self.sudo().write({'message_last_post': fields.Datetime.now()})
        if author_id and model and self.ids and message_type != 'notification' and not self._context.get('mail_create_nosubscribe'):
            self.message_subscribe([author_id], force=False)

        self._message_post_after_hook(new_message)

        return new_message
