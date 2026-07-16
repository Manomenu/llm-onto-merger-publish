#!/usr/bin/env bash
# Compile AROMRunner (and refresh all .class files for completeness).
# Pre-built bytecode shipped with the repo is Java 8; current Java 21 can
# load it, but our own AROMRunner.java needs to be compiled here.

set -euo pipefail

AROM_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$AROM_DIR"

# Build the classpath from every jar in lib/
CP=$(find lib -name "*.jar" | tr '\n' ':')

mkdir -p bin

# Only compile what our Runner needs.  hierarchy/* and debugging/* are unused
# by MergingWithoutRefactoring and their .java files contain ISO-8859 chars
# that break javac under UTF-8.
echo "Compiling AROMRunner.java + dependencies..."
javac -source 1.8 -target 1.8 \
  -cp "$CP" \
  -d bin \
  src/merging/AROMRunner.java \
  src/merging/MergingWithoutRefactoring.java \
  src/merging/OntologyConsistencyAndCoherence.java

echo "✓ build complete. bin/merging/AROMRunner.class:"
ls -la bin/merging/AROMRunner.class
