import polars as pl
from sqlite_utils import Database

db = Database(memory=True)

db.execute(
    "CREATE TABLE demo (title TEXT, done INTEGER)"
)
db.execute("INSERT INTO demo VALUES ('Write lecture', 0)")
db.execute("INSERT INTO demo VALUES ('Grade assignments', 0)")

pl.DataFrame(list(db.query("SELECT * FROM demo")))
