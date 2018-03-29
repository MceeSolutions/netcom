# -*- coding: utf-8 -*-

from odoo import models, fields, api

class Partner(models.Model):
    _name = 'res.partner'
    _inherit = 'res.partner'

    parent_account_number = fields.Char('Parent Account Number')

    @api.multi
    def name_get(self):
        res = []

        for partner in self:
            result = partner.name
            if partner.parent_account_number:
                result = str(partner.name) + " " + str(partner.parent_account_number)
            res.append((partner.id, result))
        return res

class Lead(models.Model):
    _name = "crm.lead"
    _inherit = 'crm.lead'
    

    nrc = fields.Float('NRC', track_visibility='onchange')
    mrc = fields.Float('MRC', track_visibility='onchange')
    planned_revenue = fields.Float('Expected Revenue',compute='_compute_planned_revenue', track_visibility='always')
    
    @api.one
    @api.depends('nrc','mrc')    
    def _compute_planned_revenue(self):
        self.planned_revenue = self.nrc + self.mrc
        
class EquipmentType(models.Model):
    _name = "equipment.type"
    _description = "Equipment Types"
    _order = "name"
    _inherit = ['mail.thread']

    name = fields.Char('Name', required=True, track_visibility='onchange')
    code = fields.Char('Code', required=True, track_visibility='onchange')
    active = fields.Boolean('Active', default='True')

class BrandType(models.Model):
    _name = "brand.type"
    _description = "Brand Types"
    _order = "name"
    _inherit = ['mail.thread']

    name = fields.Char('Name', required=True, track_visibility='onchange')
    code = fields.Char('Code', required=True, track_visibility='onchange')
    active = fields.Boolean('Active', default='True')

class CustomerRequest(models.Model):
    
    _name = "customer.request"
    _description = "customer request form"
    _order = "name"
    _inherit = ['res.partner']
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submit', 'Submitted'),
        ('approve', 'Approved'),
        ('reject', 'Rejected'),
        ], string='Status', readonly=True, index=True, copy=False, default='draft', track_visibility='onchange')

    @api.depends('is_company', 'parent_id.commercial_partner_id')
    def _compute_commercial_partner(self):
        return {}
            
          
    @api.multi
    def button_reset(self):
        self.write({'state': 'draft'})
        return {}
    
    @api.multi
    def button_submit(self):
        self.write({'state': 'submit'})
        return {}
    
    @api.multi
    def button_approve(self):
        self.write({'state': 'approve'})
        vals = {
            'name' : self.name,
            'company_type' : self.company_type,
            'image' : self.image,
            'parent_id' : self.parent_id,
            'street' : self.street,
            'street2' : self.street2,
            'city' : self.city,
            'state_id' : self.state_id,
            'zip' : self.zip,
            'country_id' : self.country_id,            
            'vat' : self.vat,
            'function' : self.function,
            'phone' : self.phone,
            'mobile' : self.mobile,
            'email' : self.email
        }
        self.env['res.partner'].create(vals)
        return {}
    
    @api.multi
    def button_reject(self):
        self.write({'state': 'reject'})
        return {}
    
class SubAccount(models.Model):
        
    _name = "sub.account"
    _description = "sub account form"
    _order = "parent_id"


    def _default_company(self):
        return self.env['res.company']._company_default_get('res.partner')
    
    def _write_company_type(self):
        for partner in self:
            partner.is_company = partner.company_type == 'company'

    name = fields.Char(index=True)
    
    parent_id = fields.Many2one('res.partner', string='Customer', domain="[('customer','=',True)]", index=True, ondelete='cascade')
        
    function = fields.Char(string='Description')
    
    comment = fields.Text(string='Desription')
    
    addinfo = fields.Text(string='Additional Information')
    
    child_account = fields.Char(string='Child Account Number')
    
    website = fields.Char(help="Website of Partner or Company")
    
    fax = fields.Char(help="fax")
    
    create_date = fields.Date(string='Create Date', readonly=True)
    
    contact_person = fields.Many2one('res.partner.title')
    
    company_name = fields.Many2many('Company Name')
    
    employee = fields.Boolean(help="Check this box if this contact is an Employee.")
      
    type = fields.Selection(
        [('contact', 'Contact'),
         ('invoice', 'Invoice address'),
         ('delivery', 'Shipping address'),
         ('other', 'Other address')], string='Address Type',
        default='contact',
        help="Used to select automatically the right address according to the context in sales and purchases documents.")
    street = fields.Char()
    street2 = fields.Char()
    zip = fields.Char(change_default=True)
    city = fields.Char()
    state_id = fields.Many2one("res.country.state", string='State', ondelete='restrict')
    country_id = fields.Many2one('res.country', string='Country', ondelete='restrict')
    email = fields.Char()
    
    phone = fields.Char()
    mobile = fields.Char()
    
    company_type = fields.Selection(string='Company Type',
        selection=[('person', 'Individual'), ('company', 'Company')],
        compute='_compute_company_type', inverse='_write_company_type')
    company_id = fields.Many2one('res.company', 'Company', index=True, default=_default_company)
    
    contact_address = fields.Char(compute='_compute_contact_address', string='Complete Address')
    company_name = fields.Char('Company Name') 
    
    state = fields.Selection([
        ('new', 'New'),
        ('activate', 'Activated'),
        ('suspend', 'Suspended'),
        ('terminate', 'Terminated'),
        ('cancel', 'Canceled'),
        ], string='Status', readonly=True, index=True, copy=False, default='new', track_visibility='onchange')
    
    @api.multi
    def button_new(self):
        self.write({'state': 'new'})
        return {}
    
    @api.multi
    def button_activate(self):
        self.write({'state': 'activate'})
        return {}
    
    @api.multi
    def button_suspend(self):
        self.write({'state': 'suspend'})
        return {}
    
    @api.multi
    def button_terminate(self):
        self.write({'state': 'terminate'})
        return {}
    
    @api.multi
    def button_cancel(self):
        self.write({'state': 'cancel'})
        return {}
    
class PensionManager(models.Model):
    _name = 'pen.type'
    
    name = fields.Char(string='Name')
    contact_person = fields.Char(string='Contact person')
    phone = fields.Char(string='Phone Number')
    contact_address = fields.Text(string='Contact Address')
    pfa_id = fields.Char(string='PFA ID')
    email = fields.Char(string='Email')
    notes = fields.Text(string='Notes')
    expiry_date = fields.Date(string='Expiry Date', index=True)
    renewal_date = fields.Date(string='Renewal Date', index=True)
    probation_period = fields.Integer(string='Probation Period',  index=True)
    serpac = fields.Char(string='SERPAC')
    
    
    
class Employee(models.Model):
    _inherit = 'hr.employee'
    
    pfa_id = fields.Many2one('pen.type', string='PFA ID')
        
class ProductTemplate(models.Model):
    _inherit = 'product.template'

    brand = fields.Many2one('brand.type', string='Brand', track_visibility='onchange', index=True)
    equipment_type = fields.Many2one('equipment.type', string='Equipment Type', track_visibility='onchange', index=True)
    desc = fields.Text('Remarks/Description')
    lease_price = fields.Float('Lease Price')
    



      


#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         self.value2 = float(self.value) / 100
