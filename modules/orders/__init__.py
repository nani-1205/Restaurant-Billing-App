from flask import Blueprint
bp = Blueprint('orders', __name__, template_folder='../../templates/orders')
from . import routes