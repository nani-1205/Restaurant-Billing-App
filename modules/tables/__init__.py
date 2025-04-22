# modules/tables/__init__.py
from flask import Blueprint
bp = Blueprint('tables', __name__, template_folder='../../templates/tables')
from . import routes