from app.crud.base import CRUDBase
from app.models.user import User
from app.models.airline import Airline
from app.models.supplier import Supplier
from app.models.airport import Airport
from app.models.airport_approval import AirportApproval
from app.models.route import Route
from app.models.income import IncomeRecord
from app.models.document import Document
from app.models.airline_class_master import AirlineClassMaster
from app.models.customer import Customer
from app.crud.ticket import CRUDTicket

user = CRUDBase(User)
airline = CRUDBase(Airline)
supplier = CRUDBase(Supplier)
airport = CRUDBase(Airport)
airport_approval = CRUDBase(AirportApproval)
route = CRUDBase(Route)
income = CRUDBase(IncomeRecord)
document = CRUDBase(Document)
ticket = CRUDTicket()
airline_class_master = CRUDBase(AirlineClassMaster)
customer = CRUDBase(Customer)
