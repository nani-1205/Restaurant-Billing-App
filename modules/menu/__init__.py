from flask import Blueprint
bp = Blueprint('menu', __name__, template_folder='../../templates/menu') # Specify template folder relative to blueprint location
from . import routes