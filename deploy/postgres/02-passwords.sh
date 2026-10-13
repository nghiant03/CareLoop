# Sourced by the official PostgreSQL entrypoint only on an empty data directory.
# Passwords travel through environment/psql variables, not shell command arguments.
set -eu
export CARELOOP_APP_PASSWORD="$(cat /run/secrets/postgres_app_password)"
export CARELOOP_KNOWLEDGE_READER_PASSWORD="$(cat /run/secrets/postgres_knowledge_reader_password)"
export CARELOOP_KNOWLEDGE_OPERATOR_PASSWORD="$(cat /run/secrets/postgres_knowledge_operator_password)"
psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password CARELOOP_APP_PASSWORD
\getenv reader_password CARELOOP_KNOWLEDGE_READER_PASSWORD
\getenv operator_password CARELOOP_KNOWLEDGE_OPERATOR_PASSWORD
ALTER ROLE careloop_app PASSWORD :'app_password';
ALTER ROLE careloop_knowledge_reader PASSWORD :'reader_password';
ALTER ROLE careloop_knowledge_operator PASSWORD :'operator_password';
SQL
unset CARELOOP_APP_PASSWORD CARELOOP_KNOWLEDGE_READER_PASSWORD CARELOOP_KNOWLEDGE_OPERATOR_PASSWORD
