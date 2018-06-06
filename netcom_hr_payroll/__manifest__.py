#-*- coding:utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Netcom Payroll Extend',
    'category': 'Human Resources',
    'sequence': 38,
    'website': 'http://tosinkomolafe.com',
    'depends': [
        'hr_payroll',
    ],
    'data': [
        'views/hr_payroll_report.xml',
        'views/report_netcompayslipdetails_templates.xml',
        'views/hr_payslip_view.xml',
    ],
}
