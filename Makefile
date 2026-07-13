.PHONY: test-scaffold

test-scaffold:
	python3 -m unittest discover -s tests -p 'test_*.py' -v
