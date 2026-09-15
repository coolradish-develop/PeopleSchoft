-- Runs once when the hr-db volume is created. The Okta On-prem Connector for Generic Databases needs
-- "a database user with administrator privileges to execute SQL queries": okta_ops is that user.
CREATE ROLE okta_ops LOGIN SUPERUSER PASSWORD 'scooter123!';
GRANT ALL PRIVILEGES ON DATABASE hrmaster TO okta_ops;
