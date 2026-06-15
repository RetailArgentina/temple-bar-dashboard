@echo off
set SCOPES=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/spreadsheets.readonly,https://www.googleapis.com/auth/drive.readonly
gcloud auth application-default login --scopes=%SCOPES%
