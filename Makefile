# FleetSentinel — 로컬 인프라 오케스트레이션
# 사용: make up → make topics → make smoke   (절차는 RUN.md)
#
# v3.0 전환 중: 자율주행 멀티모달 파이프라인(생성기·Flink 잡·서빙)은 재작성 대기.
# 현재 남아 있는 것은 도메인 무관 인프라 계층뿐이다. 설계 = docs/data-design-v3.md
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

smoke: ## 인프라 수용 스모크 테스트 (전 서비스 healthy + 토픽 + ES + MinIO + Kibana)
	bash scripts/smoke.sh

ha-demo: ## Kafka HA broker-kill 데모 (ADR-009, 별도 토픽 사용)
	bash scripts/ha-demo.sh
