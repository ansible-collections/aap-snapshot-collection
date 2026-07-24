COLLECTION_NAMESPACE := $(shell grep '^namespace:' galaxy.yml | awk '{print $$2}')
COLLECTION_NAME := $(shell grep '^name:' galaxy.yml | awk '{print $$2}')
COLLECTION_VERSION := $(shell grep '^version:' galaxy.yml | awk '{print $$2}')
COLLECTION_TARBALL := $(COLLECTION_NAMESPACE)-$(COLLECTION_NAME)-$(COLLECTION_VERSION).tar.gz

BUILD_DIR := build

.PHONY: build clean install lint syntax-check

build: clean
	ansible-galaxy collection build . --force --output-path=$(BUILD_DIR)
	cd $(BUILD_DIR) && sha256sum $(COLLECTION_TARBALL) > $(COLLECTION_TARBALL).sha256

clean:
	rm -rf $(BUILD_DIR)

install: build
	ansible-galaxy collection install $(BUILD_DIR)/$(COLLECTION_TARBALL) --force

lint:
	ansible-lint roles/ playbooks/

syntax-check:
	ansible-playbook --syntax-check playbooks/artifact_export.yaml
	ansible-playbook --syntax-check playbooks/artifact_import.yaml
