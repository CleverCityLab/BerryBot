ifeq ($(wildcard .env),)
	$(error Файл .env не найден!)
else
	include .env
endif

DB_URL = postgresql://$(DB_USER):$(DB_PASSWORD)@$(MAKE_DB_HOST):$(MAKE_DB_PORT)/$(DB_NAME)?sslmode=$(SSL_MODE)
MIGRATIONS_DIR = ./migrations

.PHONY: migrate rollback migrate_reload
migrate:
	yoyo apply --batch --no-config-file --database $(DB_URL) $(MIGRATIONS_DIR)

rollback:
	yoyo rollback --batch --no-config-file --database $(DB_URL) $(MIGRATIONS_DIR)

migrate_reload:
	yoyo rollback --batch --no-config-file --all --database $(DB_URL) $(MIGRATIONS_DIR)
	yoyo apply --batch --no-config-file --database $(DB_URL) $(MIGRATIONS_DIR)
	yoyo rollback --batch --no-config-file --database $(DB_URL) $(MIGRATIONS_DIR)

NETWORK = app-network
CORE_SERVICES = postgres
WORK_SERVICES = berry-bot
SERVICES := $(if $(SERVICE),$(SERVICE),$(WORK_SERVICES))

.PHONY: core
core:
	@echo "Проверка core-сервисов"
	@docker compose up -d $(CORE_SERVICES)

.PHONY: build up stop rm down ps logs startup

build: core
	docker compose build $(SERVICES)

up: build
	docker compose up -d $(SERVICES)

stop:
	docker compose stop $(SERVICES)

rm:
	@echo "Удаляю $(SERVICES)  (CLEAN=$(CLEAN)) …"
	-@docker compose stop $(SERVICES)

ifeq ($(CLEAN),1)
	@docker compose rm -fsv $(SERVICES)
	@$(foreach s, $(SERVICES), $(foreach i, $(shell docker compose images -q $(s)), docker rmi -f $(i) && ) echo Done.)
else
	@docker compose rm -fs $(SERVICES)
endif

down:

	@echo "Останавливаю и удаляю все сервисы"
	@docker compose down $(if $(filter 1,$(CLEAN)),--volumes --rmi all)

ifeq ($(CLEAN),1)
	@echo "Удаляю образы рабочих сервисов: $(WORK_SERVICES)"
	@$(foreach s, $(WORK_SERVICES), \
		$(foreach i, $(shell docker compose images -q $(s)), docker rmi -f $(i) && ) echo Done.)
endif

ps:
	docker compose ps $(SERVICES)

logs:
	docker compose logs -f $(SERVICES)

startup: up
	@echo "Применяю миграции через migrate_reload..."
	@$(MAKE) migrate_reload --no-print-directory
	@echo "Стартовая инициализация завершена."