# FleetSentinel — 로컬 인프라 오케스트레이션
# 사용: make up → make topics → make smoke   (절차는 RUN.md)
#
# 이 Makefile은 로컬 인프라 계층만 다룬다. Kafka→Flink→ClickHouse 파이프라인은 미구현(P2·P3)이라
# 기동해도 데이터가 흐르지 않는다. 차량 측 구현 테스트와 대시보드는 인프라 없이 돈다 — RUN.md §6·§7.
# 설계 = docs/sdd.md
COMPOSE := docker compose -f infra/docker-compose.yml
export COMPOSE

.DEFAULT_GOAL := help
.PHONY: help up down restart ps logs topics smoke clean pull config ha-demo

help: ## 명령 목록
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

config: ## compose 문법 검증
	@$(COMPOSE) config -q && echo "compose config OK"

pull: ## 이미지 사전 당기기
	$(COMPOSE) pull

up: ## 스택 기동 (헬시까지 대기)
	@$(COMPOSE) up -d --wait; rc=$$?; $(COMPOSE) ps; exit $$rc

down: ## 스택 종료 (볼륨 유지)
	$(COMPOSE) down

clean: ## 스택 종료 + 볼륨/데이터 삭제
	$(COMPOSE) down -v

restart: down up ## 재기동

ps: ## 상태
	$(COMPOSE) ps

logs: ## 로그 팔로우 (make logs S=kafka1)
	$(COMPOSE) logs -f $(S)

topics: ## Kafka 토픽 부트스트랩 (RF=3 / min.insync.replicas=2)
	bash scripts/create-topics.sh

smoke: ## 인프라 수용 스모크 테스트 (전 서비스 healthy + 토픽 + ClickHouse + MinIO)
	bash scripts/smoke.sh

ha-demo: ## Kafka HA broker-kill 데모 (ADR-009, 별도 토픽 사용)
	bash scripts/ha-demo.sh
