.PHONY: deploy health-check monitor stop logs clean verify help

# The webapp's port, defined once. It used to be hardcoded as 5000 in every
# health check, which is the Pico's port, not ours. So health-check never
# passed and monitor restarted a perfectly healthy container every 30s.
PORT ?= 8000
URL  := http://localhost:$(PORT)

# Default target
help:
	@echo "Keybot Webapp Deployment Automation"
	@echo "===================================="
	@echo ""
	@echo "Available targets:"
	@echo "  make deploy       - Deploy/restart the webapp (docker compose down && up)"
	@echo "  make health-check - Check if webapp is running and responsive"
	@echo "  make monitor      - Keep webapp running (restart if needed)"
	@echo "  make stop         - Stop the webapp container"
	@echo "  make logs         - Show container logs (tail -f)"
	@echo "  make clean        - Stop container and remove data"
	@echo "  make verify       - Deploy, then confirm the page loads"
	@echo "  make help         - Show this help message"
	@echo ""
	@echo "Examples:"
	@echo "  make deploy              # Deploy now"
	@echo "  make monitor             # Keep running in background"
	@echo ""

# Deploy: restart docker with updated configuration
deploy:
	@echo "🚀 Deploying keybot webapp..."
	@docker compose down 2>/dev/null || true
	@sleep 2
	@docker compose up -d
	@echo "⏳ Waiting for app to be ready..."
	@ok=0; \
	for i in $$(seq 1 30); do \
		if curl -s -o /dev/null --max-time 3 $(URL)/ 2>/dev/null; then ok=1; break; fi; \
		sleep 1; \
	done; \
	if [ "$$ok" = "1" ]; then \
		echo "App is ready at $(URL)"; \
	else \
		echo "App did not start within 30 seconds"; \
		docker compose logs --tail=20; \
		exit 1; \
	fi

# Health check: verify app is responding
health-check:
	@code=$$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 $(URL)/ 2>/dev/null || echo 000); \
	if [ "$$code" = "200" ]; then \
		echo "Webapp at $(URL): OK (HTTP $$code)"; \
		exit 0; \
	else \
		echo "Webapp at $(URL): not responding (HTTP $$code)"; \
		echo "This checks the webapp only. The Pico is checked from the app's Device Status panel."; \
		exit 1; \
	fi

# Monitor: continuous health check with auto-restart
monitor:
	@echo "🔍 Starting health monitor (Ctrl+C to stop)..."
	@while true; do \
		if ! curl -s -o /dev/null --max-time 10 $(URL)/ 2>/dev/null; then \
			echo "[$$(date)] App not responding at $(URL) - restarting..."; \
			$(MAKE) deploy > /dev/null 2>&1; \
		else \
			echo "[$$(date)] OK"; \
		fi; \
		sleep 30; \
	done

# Stop the container
stop:
	@echo "Stopping container..."
	@docker compose down

# Show logs
logs:
	@docker compose logs -f

# Clean: stop and remove volumes
clean:
	@echo "⚠️  Removing container and data..."
	@docker compose down -v
	@echo "Done"

# Verify deployment: bring it up, then confirm the page actually loads.
verify: deploy
	@echo ""
	@if curl -s $(URL)/ | grep -q "keybot"; then \
		echo "Page loads at $(URL)"; \
	else \
		echo "Page did not load at $(URL)"; \
		exit 1; \
	fi
