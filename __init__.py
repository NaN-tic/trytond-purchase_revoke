# This file is part purchase_revoke module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import purchase

def register():
    Pool.register(
        purchase.Purchase,
        module='purchase_revoke', type_='model')
    Pool.register(
        purchase.PurchaseCreatePendingMoves,
        module='purchase_revoke', type_='wizard')
