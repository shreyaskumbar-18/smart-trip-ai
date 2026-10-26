# SmartTrip AI database setup

MySQL is the default database. The default database name is `smarttrip`.

- `create_mysql_database.sql` creates the database if it does not exist.
- Django migrations create and update the application schema.
- `python manage.py seed_data` loads the demonstration destinations and attractions.

This package does not include a database dump or a local database file. Back up an existing database and inspect its migration history before applying migrations. Do not drop or recreate your existing `smarttrip` database to install the application.

For isolated local development only, set `DB_ENGINE=sqlite` in `.env`. Django will create the SQLite database when migrations run.
