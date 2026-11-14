.PHONY: test serve scan ipa
test:
	cd backend && python -m pytest -q
serve:
	cd backend && python -m renko_scalper -c config.yaml serve
scan:
	cd backend && python -m renko_scalper -c config.yaml scan
ipa:            # needs macOS + Xcode + `brew install xcodegen`
	./scripts/build_ipa.sh
