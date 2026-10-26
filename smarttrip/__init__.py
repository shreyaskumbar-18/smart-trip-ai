"""SmartTrip project package."""
try:
    import pymysql
    pymysql.install_as_MySQLdb()
except ImportError:
    # SQLite is the default; PyMySQL is required only for MySQL mode.
    pass
