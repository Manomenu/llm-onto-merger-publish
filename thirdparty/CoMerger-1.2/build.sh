#!/usr/bin/env bash
# Build CoMerger via Maven and emit a self-contained classpath file.
#
# Steps:
#   1. `mvn compile`                                    → target/classes/
#   2. `mvn dependency:build-classpath -Dmdep.outputFile=target/cp.txt`
#                                                       → flat classpath with all deps
#
# Output (consumed by comerger.sh):
#   Source_Code/target/classes/                         compiled .class files
#   Source_Code/target/cp.txt                           single-line classpath of all deps
#
# Maven is required (project has 30+ dependencies — manual classpath is impractical).
# Install with: brew install maven

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="$REPO_DIR/Source_Code"
# Local Maven repository (avoids polluting ~/.m2/ with CoMerger-specific deps).
# Everything Maven downloads lives inside thirdparty/CoMerger-1.2/.m2-local/.
LOCAL_REPO="$REPO_DIR/.m2-local"

if ! command -v mvn >/dev/null 2>&1; then
  echo "ERROR: mvn (Apache Maven) is not on PATH." >&2
  echo "Install with:  brew install maven" >&2
  echo "Then re-run this script." >&2
  exit 1
fi

cd "$SRC_DIR"
mkdir -p "$LOCAL_REPO"

# CoMerger's pom.xml uses Windows backslashes inside <systemPath> for the
# external-jars entries (jung / matrix / ws4j / snowball / align / sesame / agg).
# Maven on macOS/Linux doesn't normalise these, so it can't find the JARs and the
# build fails.  Patch pom.xml in place — only on <systemPath> lines — first time
# we encounter backslashes there.  Backup goes to pom.xml.bak.
if grep -q '<systemPath>.*\\' pom.xml; then
  echo "==> patching pom.xml: '\\' → '/' on <systemPath> lines (backup: pom.xml.bak)"
  sed -i.bak '/<systemPath>/s|\\|/|g' pom.xml
fi

# CoMerger keeps sources in src/ (Eclipse layout) but Maven defaults to
# src/main/java/.  Without <sourceDirectory> in <build>, mvn compile says
# "No sources to compile" and produces an empty target/.  Inject the override
# once (idempotent: skip if already present).
if ! grep -q '<sourceDirectory>' pom.xml; then
  echo "==> patching pom.xml: adding <sourceDirectory>src</sourceDirectory>"
  sed -i.bak2 's|<build>|<build>\
		<sourceDirectory>src</sourceDirectory>|' pom.xml
fi

# CoMerger's repo is MISSING the genericMerge package and depends on Tomcat
# servlet APIs that aren't on the classpath.  These ONLY affect GUI / web UI /
# evaluator / servlets code — none of which is reachable from CoMergerRunner.
#
# Maven compiler plugin's <excludes> config DOES NOT WORK for these paths
# (tried v3.3 and v3.13, with various pattern shapes — Maven simply ignores
# them).  Brute force instead: temporarily rename the offending directories
# so Maven can't find them.  Restore-friendly: each rename adds an "_skip"
# suffix; if already renamed (from a previous build) the move is skipped.
#
# Touch this only ONCE — subsequent builds reuse the already-renamed state.
EXCLUDED_STORE="${SRC_DIR}/.excluded_sources"
mkdir -p "$EXCLUDED_STORE"
SKIP_PATHS=(
  # UI / web frontend — no dep from holisticMerge
  "src/fusion/comerger/general/gui"
  "src/fusion/comerger/general/visualization"
  "src/fusion/comerger/servlets"
  # Evaluator + batch runner — depend on missing genericMerge package
  "src/fusion/comerger/algorithm/merger/holisticMerge/evaluator"
  "src/fusion/comerger/algorithm/merger/holisticMerge/localTest/batch"
  # Partitioner (SeeCOnt) — separate alignment tool, not used by holistic merge
  "src/fusion/comerger/algorithm/partitioner"
  # Analysis utilities — depend on general.gui
  "src/fusion/comerger/general/analysis"
  # gernalAnalysis (typo in original repo) — uses partitioner + output internals
  "src/fusion/comerger/general/gernalAnalysis"
  # Matcher (separate alignment tool) — uses missing NamedMatrix class
  "src/fusion/comerger/algorithm/matcher"
  # Individual files with deps on partitioner / general.gui / missing classes —
  # but rest of the package is needed (Alignment, Mapping in general/output;
  # BuildModel, Configuration, Data, LingComp, StruComp, Parameters in general/cc).
  "src/fusion/comerger/general/output/SaveOutput.java"
  "src/fusion/comerger/general/output/AlignmentSelector.java"
  "src/fusion/comerger/general/cc/Cleaning_Allthings.java"
  "src/fusion/comerger/general/cc/Controller.java"
  "src/fusion/comerger/general/cc/Data.java"
  "src/fusion/comerger/general/cc/BuildModel.java"
  # Consistency runners that pull in servlets.MatchingProcess (rest of
  # consistency/ — Opinion, SLogic, DeductionSL, etc. — is fine).
  "src/fusion/comerger/algorithm/merger/holisticMerge/consistency/ConsistencyProcess.java"
  "src/fusion/comerger/algorithm/merger/holisticMerge/consistency/LocalRun_Consistency.java"
)
for p in "${SKIP_PATHS[@]}"; do
  stash="$EXCLUDED_STORE/$(echo "$p" | tr '/' '_')"
  if [ -e "$p" ] && [ ! -e "$stash" ]; then
    echo "==> stashing out of src/: $p → $stash"
    mv "$p" "$stash"
  fi
done

# Replace StatisticTest.java with a minimal stub. The original imports classes
# from excluded packages (evaluator/HEvaluator, servlets/MatchingProcess, plus
# missing GenerateOutput) but HolisticMerger / HBuilder only use the static
# `result` HashMap field — a 5-line stub covers that.
ORIG_STAT="src/fusion/comerger/algorithm/merger/holisticMerge/localTest/StatisticTest.java"
STAT_STASH="$EXCLUDED_STORE/StatisticTest.java.original"
if [ -f "$ORIG_STAT" ] && ! grep -q "lightweight stub" "$ORIG_STAT"; then
  echo "==> replacing $ORIG_STAT with lightweight stub"
  cp "$ORIG_STAT" "$STAT_STASH"
  cat > "$ORIG_STAT" <<'EOF'
package fusion.comerger.algorithm.merger.holisticMerge.localTest;

import java.util.HashMap;

// Lightweight stub replacing the original StatisticTest, which depended on
// classes from excluded packages (evaluator/HEvaluator, servlets/MatchingProcess)
// plus a missing GenerateOutput class.  HolisticMerger and HBuilder only use
// the static `result` HashMap — this minimal version covers that.
public class StatisticTest {
    public static HashMap<String, String> result = new HashMap<>();
}
EOF
fi

echo "==> mvn compile  (CoMerger Source_Code)"
echo "    local repo:  $LOCAL_REPO  (first build downloads ~100MB of deps here)"
mvn -q compile -Dmaven.repo.local="$LOCAL_REPO"

echo "==> mvn dependency:build-classpath  (writing target/cp.txt)"
mvn -q dependency:build-classpath -Dmaven.repo.local="$LOCAL_REPO" \
    -Dmdep.outputFile=target/cp.txt

# Build absolute paths to the system-scope external-jars (they're scope=system in pom).
# Maven includes them in build-classpath since version 3.1+, but defensively add them.
EXT_JARS=$(find external-jars -name "*.jar" | tr '\n' ':')

# Final classpath: target/classes + Maven-resolved deps + system-scope JARs
echo "${SRC_DIR}/target/classes:$(cat target/cp.txt):${EXT_JARS}" > target/cp_full.txt

echo "✓ Build complete."
echo "  classes:       ${SRC_DIR}/target/classes/"
echo "  classpath:     ${SRC_DIR}/target/cp_full.txt"
echo "  runner class:  fusion.comerger.algorithm.merger.holisticMerge.CoMergerRunner"
