PYTHON ?= python
PYTHON_SOURCE_DIRS_TO_CHECK = mcp/blmcp/ addon/blender_mcp_addon/ chat_client/

define HELP_TEXT

Targets
   * test:              Run unit tests.
   * test_integration:  Run integration tests (requires BLENDER_BIN).
                        Loads .env if present (e.g. ANTHROPIC_API_KEY).
                        Uses .test_venv (delete to force a rebuild).

     List all tests:    make test_integration TESTS_LIST=1
     Run tests:         make test_integration TESTS=TestChatClient.test_name
     Multiple tests:    make test_integration TESTS=test_one:test_two
   * format:            Auto-format Python sources with autopep8.
   * readme_update:     Regenerate the tools listing in readme.rst.

Static Source Code Checking
   * check_license:   Verify SPDX headers in all Python files.
   * check_ascii:     Reject non-ASCII characters in sources.
   * check_mypy:      Run mypy type checking.
   * check_pylint:    Run pylint linting.
   * check_ruff:      Run ruff linting.
   * check_vulture:   Run vulture dead-code detection.
   * check_all:       Run all checks (ruff, mypy, vulture, license, ascii).

Reference Data
   * update_reference_manual:
     Copy RST and Python files from a Blender manual checkout.

     Usage: make update_reference_manual MANUAL_DIR=/path/to/manual

   * update_reference_api:
     Copy RST files from a Blender API reference build.

     Usage: make update_reference_api API_DIR=/path/to/api

endef
export HELP_TEXT

help:
	@echo "$$HELP_TEXT"

test:
	$(PYTHON) tests/test_tool_listing.py -v
	$(PYTHON) tests/test_mcp_server.py -v
	$(PYTHON) tests/test_background_server.py -v

test_integration:
ifdef TESTS_LIST
	@$(PYTHON) -c "import unittest, sys; sys.path.insert(0, '.'); \
	from tests.integration.test_chat_client import TestChatClient; \
	[print(t.id().rsplit('.', 1)[-2].split('.')[-1] + '.' + t.id().rsplit('.', 1)[-1]) for t in unittest.TestLoader().loadTestsFromTestCase(TestChatClient)]"
else
	@test -f .env && export $$(grep -v '^\s*#' .env | xargs) || true; \
	$(PYTHON) tests/integration/test_chat_client.py -v $$(echo '$(TESTS)' | tr ':' ' ')
endif

format:
	autopep8 --in-place --recursive mcp/ addon/

check_license:
	@$(PYTHON) scripts/check_license.py

check_ascii:
	@! pcregrep -rn --include='\.py$$' --include='\.toml$$' '[^\x00-\x7F]' mcp/ addon/ chat_client/ || \
		{ echo "ERROR: non-ASCII characters found"; exit 1; }

check_mypy:
	@! .venv/bin/mypy $(PYTHON_SOURCE_DIRS_TO_CHECK) scripts/ 2>&1 | grep -v '^stubs/' | grep ': error:' || \
		{ echo "mypy: found errors"; exit 1; }

check_pylint:
	pylint $(PYTHON_SOURCE_DIRS_TO_CHECK) \
		--disable=C0103,C0115,C0116,C0209,C0413,C0415,R0801,R0903,R0912,R0914,R0915,W0122

check_ruff:
	ruff check $(PYTHON_SOURCE_DIRS_TO_CHECK)

check_vulture:
	vulture $(PYTHON_SOURCE_DIRS_TO_CHECK) \
		--ignore-decorators '@mcp.tool,@mcp.prompt' \
		--ignore-names 'bl_*,draw,execute,exclude' \
		--min-confidence 61

check_all: check_ruff check_mypy check_vulture check_license check_ascii

readme_update:
	$(PYTHON) scripts/readme_update_from_tools.py

update_reference_manual:
	@test -n "$(MANUAL_DIR)" || { echo "Usage: make update_reference_manual MANUAL_DIR=/path/to/blender/manual"; exit 1; }
	$(PYTHON) scripts/update_reference_manual.py "$(MANUAL_DIR)"

update_reference_api:
	@test -n "$(API_DIR)" || { echo "Usage: make update_reference_api API_DIR=/path/to/api"; exit 1; }
	$(PYTHON) scripts/update_reference_api.py "$(API_DIR)"
