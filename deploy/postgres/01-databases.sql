-- First initialization only. The separate migrate service owns application DDL.
-- 02-passwords.sh provisions credentials from private Compose secrets.
CREATE ROLE careloop_app LOGIN;
CREATE ROLE careloop_knowledge_reader LOGIN;
CREATE ROLE careloop_knowledge_operator LOGIN;

CREATE DATABASE careloop_clinical OWNER careloop_admin;
CREATE DATABASE careloop_knowledge OWNER careloop_admin;

REVOKE ALL ON DATABASE careloop_clinical FROM PUBLIC;
REVOKE ALL ON DATABASE careloop_knowledge FROM PUBLIC;
GRANT CONNECT ON DATABASE careloop_clinical TO careloop_app;
GRANT CONNECT ON DATABASE careloop_knowledge
    TO careloop_knowledge_reader, careloop_knowledge_operator;

\connect careloop_clinical
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO careloop_app;
ALTER DEFAULT PRIVILEGES FOR ROLE careloop_admin IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO careloop_app;
ALTER DEFAULT PRIVILEGES FOR ROLE careloop_admin IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO careloop_app;

\connect careloop_knowledge
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public
    TO careloop_knowledge_reader, careloop_knowledge_operator;
ALTER DEFAULT PRIVILEGES FOR ROLE careloop_admin IN SCHEMA public
    GRANT SELECT ON TABLES TO careloop_knowledge_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE careloop_admin IN SCHEMA public
    GRANT SELECT, INSERT ON TABLES TO careloop_knowledge_operator;
ALTER DEFAULT PRIVILEGES FOR ROLE careloop_admin IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO careloop_knowledge_operator;
