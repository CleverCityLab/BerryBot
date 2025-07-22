FROM ubuntu:latest
LABEL authors="Sergey"

ENTRYPOINT ["top", "-b"]