# This file is part purchase_revoke module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool

def register():
    Pool.register(
        module='purchase_revoke', type_='model')
    Pool.register(
        module='purchase_revoke', type_='wizard')
    Pool.register(
        module='purchase_revoke', type_='report')
