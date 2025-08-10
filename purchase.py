# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.pool import Pool, PoolMeta
from trytond.model import Workflow, ModelView
from trytond.model import fields
from trytond.transaction import Transaction
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.pyson import Bool, Eval
from trytond.wizard import StateAction, Wizard


class Purchase(metaclass=PoolMeta):
    __name__ = 'purchase.purchase'

    ignored_moves = fields.Function(fields.One2Many('stock.move', None,
        'Ignored Moves'), 'get_ignored_moves')

    @classmethod
    def __setup__(cls):
        super(Purchase, cls).__setup__()
        cls._transitions |= set((
                ('confirmed', 'done'),
                ))
        cls._buttons.update({
                'revoke': {
                    'invisible': ~Eval('state').in_(
                        ['confirmed', 'processing']),
                    'depends': ['state'],
                    },
                'create_pending_moves': {
                    'invisible': (~Eval('state').in_(['processing', 'done'])
                        | ~Bool(Eval('ignored_moves', []))),
                    'depends': ['state', 'ignored_moves'],
                    },
                })

    @classmethod
    def get_ignored_moves(cls, purchases, name):
        res = dict((x.id, None) for x in purchases)
        for purchase in purchases:
            moves = []
            for line in purchase.lines:
                moves += [m.id for m in line.moves_ignored]
            res[purchase.id] = moves
        return res

    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def revoke(cls, purchases):
        cls.handle_shipments(purchases)
        cls.handle_invoices(purchases)

    @classmethod
    def handle_shipments(cls, purchases):
        pool = Pool()
        Move = pool.get('stock.move')
        Shipment = pool.get('stock.shipment.in')
        ShipmentReturn = pool.get('stock.shipment.in.return')
        HandleShipmentException = pool.get(
            'purchase.handle.shipment.exception', type='wizard')

        def _check_moves(purchase):
            moves = []
            for key in [('shipments', 'incoming_moves'),
                    ('shipment_returns', 'moves')]:
                shipments, shipment_moves = key[0], key[1]
                for shipment in getattr(purchase, shipments):
                    for move in getattr(shipment, shipment_moves):
                        if move.state not in ('cancelled', 'draft', 'done'):
                            moves.append(move)
            return moves

        for purchase in purchases:
            moves = _check_moves(purchase)
            picks = [shipment for shipment in
                list(purchase.shipments) + list(purchase.shipment_returns)
                if shipment.state not in ('waiting', 'draft', 'done')]
            if moves or picks:
                names = ', '.join(m.rec_name for m in (moves + picks)[:5])
                if len(names) > 5:
                    names += '...'
                raise UserError(gettext('purchase_revoke.msg_can_not_revoke',
                    record=purchase.rec_name,
                    names=names))

            Shipment.cancel([shipment for shipment in purchase.shipments
                if shipment.state in ('draft', 'waiting')])
            ShipmentReturn.cancel([shipment for shipment in purchase.shipment_returns
                if shipment.state in ('draft', 'waiting')])

            # ensure has all moves from purchase Lines
            moves = [move for line in purchase.lines for move in line.moves
                if move.state == 'draft']
            if moves:
                Move.cancel(moves)

            moves = [move for line in purchase.lines for move in line.moves
                if move.state == 'cancelled']
            skip = set()
            for line in purchase.lines:
                skip |= set(line.moves_ignored + line.moves_recreated)
            pending_moves = [x for x in moves if not x in skip]

            with Transaction().set_context(active_model=cls.__name__,
                    active_ids=[purchase.id], active_id=purchase.id):
                session_id, _, _ = HandleShipmentException.create()
                handle_shipment_exception = HandleShipmentException(session_id)
                handle_shipment_exception.ask.recreate_moves = []
                handle_shipment_exception.ask.domain_moves = pending_moves
                handle_shipment_exception.transition_handle()
                HandleShipmentException.delete(session_id)

    @classmethod
    def handle_invoices(cls, purchases):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        HandleInvoiceException = pool.get(
            'purchase.handle.invoice.exception', type='wizard')

        for purchase in purchases:
            if purchase.invoice_method == 'manual':
                cls.manual_invoice([purchase])
            Invoice.cancel([invoice for invoice in purchase.invoices
                if invoice.state == 'draft'])

            cancel_invoices = [invoice for invoice in purchase.invoices
                if invoice.state == 'cancelled']
            skip = set(purchase.invoices_ignored + purchase.invoices_recreated)
            pending_invoices = [i for i in cancel_invoices if not i in skip]

            with Transaction().set_context(active_model=cls.__name__,
                    active_ids=[purchase.id], active_id=purchase.id):
                session_id, _, _ = HandleInvoiceException.create()
                handle_invoice_exception = HandleInvoiceException(session_id)
                handle_invoice_exception.ask.recreate_invoices = []
                handle_invoice_exception.ask.domain_invoices = pending_invoices
                handle_invoice_exception.transition_handle()
                HandleInvoiceException.delete(session_id)

    @classmethod
    @ModelView.button_action('purchase_revoke.act_purchase_create_pending_moves_wizard')
    def create_pending_moves(cls, purchases):
        pass


class PurchaseCreatePendingMoves(Wizard):
    "Purchase Create Pending Moves"
    __name__ = 'purchase.purchase.create_pending_moves'
    start = StateAction('purchase.act_purchase_form')

    def do_start(self, action):
        pool = Pool()
        Uom = pool.get('product.uom')
        Purchase = pool.get('purchase.purchase')
        Line = pool.get('purchase.line')

        new_purchases = []
        for purchase in self.records:
            ignored_moves = purchase.ignored_moves
            if not ignored_moves:
                continue

            products = dict((move.product.id, 0) for move in ignored_moves)
            purchase_units = dict((move.product.id, move.product.purchase_uom)
                for move in ignored_moves)

            for move in ignored_moves:
                from_uom = move.unit
                to_uom = move.product.purchase_uom
                if from_uom != to_uom:
                    qty = Uom.compute_qty(from_uom, move.quantity,
                        to_uom, round=False)
                else:
                    qty = move.quantity
                products[move.product.id] += qty

            new_purchase, = Purchase.copy([purchase], {'lines': []})

            def default_quantity(data):
                product_id = data.get('product')
                quantity = data.get('quantity')
                if product_id and products.get(product_id):
                    return products[product_id]
                return quantity

            def default_sale_unit(data):
                product_id = data.get('product')
                unit_id = data.get('unit')
                if product_id and purchase_units.get(product_id):
                    return purchase_units[product_id]
                return unit_id

            Line.copy(purchase.lines, default={
                'purchase': new_purchase,
                'quantity': default_quantity,
                'unit': default_sale_unit,
                })

            new_purchases.append(new_purchase)

        data = {'res_id': [s.id for s in new_purchases]}
        if len(new_purchases) == 1:
            action['views'].reverse()
        return action, data
