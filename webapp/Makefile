.PHONY: deploy health-check monitor stop logs clean help

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
	@for i in {1..30}; do \
		if curl -s http://localhost:5000/api/device/status > /dev/null 2>&1; then \
			echo "✅ App is ready at http://localhost:5000"; \
			exit 0; \
		fi; \
		sleep 1; \
	done
	@echo "❌ App did not start within 30 seconds"
	@docker compose logs --tail=20
	@exit 1

# Health check: verify app is responding
health-check:
	@if curl -s --max-time 5 http://localhost:5000/api/device/status > /dev/null 2>&1; then \
		echo "✅ Webapp is healthy"; \
		exit 0; \
	else \
		echo "❌ Webapp is not responding"; \
		exit 1; \
	fi

# Monitor: continuous health check with auto-restart
monitor:
	@echo "🔍 Starting health monitor (Ctrl+C to stop)..."
	@while true; do \
		if ! curl -s --max-time 5 http://localhost:5000/api/device/status > /dev/null 2>&1; then \
			echo "[$(date)] ⚠️  App not responding - restarting..."; \
			$(MAKE) deploy > /dev/null 2>&1; \
		else \
			echo "[$(date)] ✅ OK"; \
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

# Verify deployment
verify: deploy
	@echo ""
	@echo "Verifying deployment..."
	@if curl -s http://localhost:5000/ | grep -q "keybot"; then \
		echo "✅ HTML page loads"; \
	else \
		echo "❌ HTML page not loading"; \
		exit 1; \
	fi
	@if curl -s http://localhost:5000/static/app.js | grep -q "updateDeviceIndicator"; then \
		echo "✅ New device indicator code present"; \
	else \
		echo "⚠️  Device indicator code not found"; \
	fi
	@if curl -s http://localhost:5000/static/app.js | grep -q "addToRecentScripts"; then \
		echo "✅ Recent scripts code present"; \
	else \
		echo "⚠️  Recent scripts code not found"; \
	fi
	@echo ""
	@echo "Webapp ready at http://localhost:5000"
