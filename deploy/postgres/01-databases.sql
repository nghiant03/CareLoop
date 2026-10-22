-- First initialization only. The separate migrate service owns application DDL.
-- A single admin role owns both databases; runtime role separation is out of scope.
CREATE DATABASE careloop_clinical OWNER careloop_admin;
CREATE DATABASE careloop_knowledge OWNER careloop_admin;

REVOKE ALL ON DATABASE careloop_clinical FROM PUBLIC;
REVOKE ALL ON DATABASE careloop_knowledge FROM PUBLIC;
