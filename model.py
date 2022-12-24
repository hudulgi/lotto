from .setup import *


class ModelLottoItem(ModelBase):
    P = P
    __tablename__ = 'lotto_item'
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = P.package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    round = db.Column(db.String)
    count = db.Column(db.Integer)
    data = db.Column(db.JSON)
    img = db.Column(db.String)

    def __init__(self):
        self.created_time = datetime.now()
