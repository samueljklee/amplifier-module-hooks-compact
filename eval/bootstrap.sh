#!/usr/bin/env bash
# Create eval fixture directories required by test-cases.yaml and simulate_all_filters.py.
#
# Usage:
#   ./eval/bootstrap.sh                  # creates fixtures in ./eval/fixtures/
#   HOOKS_COMPACT_EVAL_FIXTURES=/tmp ./eval/bootstrap.sh  # creates in /tmp
#
# Idempotent — checks existence before creating. Safe to re-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
FIXTURES_DIR="${HOOKS_COMPACT_EVAL_FIXTURES:-$SCRIPT_DIR/fixtures}"

mkdir -p "$FIXTURES_DIR"
echo "Creating eval fixtures in: $FIXTURES_DIR"

# ── Helper ──────────────────────────────────────────────────────────────────
create_if_missing() {
  local dir="$1"
  if [ -d "$dir" ]; then
    echo "  ✓ $dir (exists)"
    return 0
  fi
  mkdir -p "$dir"
  echo "  + $dir (created)"
}

write_if_missing() {
  local file="$1"
  local content="$2"
  if [ -f "$file" ]; then
    return 0
  fi
  mkdir -p "$(dirname "$file")"
  echo "$content" > "$file"
}

# ── 1. test-rust-project ──────────────────────────────────────────────────
# Used by: git-commit, cargo-test-pass, cargo-build-clean
DIR="$FIXTURES_DIR/test-rust-project"
create_if_missing "$DIR"
write_if_missing "$DIR/Cargo.toml" '[package]
name = "test_project"
version = "0.1.0"
edition = "2021"'
write_if_missing "$DIR/src/main.rs" 'fn main() {
    println!("Hello, world!");
}

#[cfg(test)]
mod tests {
    #[test]
    fn test_add() { assert_eq!(2 + 2, 4); }
    #[test]
    fn test_sub() { assert_eq!(5 - 3, 2); }
    #[test]
    fn test_mul() { assert_eq!(3 * 4, 12); }
    #[test]
    fn test_div() { assert_eq!(10 / 2, 5); }
}'
# Init git repo if needed (for git-commit scenario)
if [ ! -d "$DIR/.git" ]; then
  (cd "$DIR" && git init -q && git add -A && git commit -q -m "init" 2>/dev/null) || true
fi

# ── 2. test-rust-fail ────────────────────────────────────────────────────
# Used by: cargo-test-fail
DIR="$FIXTURES_DIR/test-rust-fail"
create_if_missing "$DIR"
write_if_missing "$DIR/Cargo.toml" '[package]
name = "test_fail"
version = "0.1.0"
edition = "2021"'
write_if_missing "$DIR/src/main.rs" 'fn main() {}

#[cfg(test)]
mod tests {
    #[test]
    fn test_pass() { assert_eq!(1, 1); }
    #[test]
    fn test_fail_one() { assert_eq!(1, 2, "expected 2 but got 1"); }
    #[test]
    fn test_fail_two() { panic!("intentional panic for eval"); }
}'

# ── 3. test-node-project ─────────────────────────────────────────────────
# Used by: npm-test-pass, npm-build-success
DIR="$FIXTURES_DIR/test-node-project"
create_if_missing "$DIR"
write_if_missing "$DIR/package.json" '{
  "name": "test-node-project",
  "version": "1.0.0",
  "scripts": {
    "test": "mocha",
    "build": "echo Build completed successfully"
  },
  "devDependencies": { "mocha": "^10.0.0" }
}'
write_if_missing "$DIR/test/test.js" "const assert = require('assert');
describe('Math', function() {
  it('should add', function() { assert.strictEqual(2+2, 4); });
  it('should sub', function() { assert.strictEqual(5-3, 2); });
  it('should mul', function() { assert.strictEqual(3*4, 12); });
  it('should div', function() { assert.strictEqual(10/2, 5); });
});"
# npm install if node_modules missing
if [ ! -d "$DIR/node_modules" ] && command -v npm &>/dev/null; then
  (cd "$DIR" && npm install --silent 2>/dev/null) || true
fi

# ── 4. test-node-fail ────────────────────────────────────────────────────
# Used by: npm-test-fail
DIR="$FIXTURES_DIR/test-node-fail"
create_if_missing "$DIR"
write_if_missing "$DIR/package.json" '{
  "name": "test-node-fail",
  "version": "1.0.0",
  "scripts": { "test": "mocha" },
  "devDependencies": { "mocha": "^10.0.0" }
}'
write_if_missing "$DIR/test/test.js" "const assert = require('assert');
describe('Failing', function() {
  it('should pass', function() { assert.strictEqual(1, 1); });
  it('should fail one', function() { assert.strictEqual(1, 2); });
  it('should fail two', function() { throw new Error('intentional'); });
});"
if [ ! -d "$DIR/node_modules" ] && command -v npm &>/dev/null; then
  (cd "$DIR" && npm install --silent 2>/dev/null) || true
fi

# ── 5. test-rust-clippy ──────────────────────────────────────────────────
# Used by: cargo-clippy, clippy-fix-continuation
DIR="$FIXTURES_DIR/test-rust-clippy"
create_if_missing "$DIR"
write_if_missing "$DIR/Cargo.toml" '[package]
name = "test_clippy"
version = "0.1.0"
edition = "2021"'
write_if_missing "$DIR/src/main.rs" '#![allow(dead_code)]
fn main() {
    let x = 5;
    // clippy::needless_return
    return;
}

fn redundant_clone() {
    let s = String::from("hello");
    let _t = s.clone();  // clippy::redundant_clone (s not used after)
}

fn manual_map() {
    let x: Option<i32> = Some(5);
    let _y = match x {
        Some(v) => Some(v * 2),
        None => None,
    };  // clippy::manual_map
}'

# ── 6. test-node-eslint ──────────────────────────────────────────────────
# Used by: eslint-errors
DIR="$FIXTURES_DIR/test-node-eslint"
create_if_missing "$DIR"
write_if_missing "$DIR/package.json" '{
  "name": "test-node-eslint",
  "version": "1.0.0",
  "devDependencies": { "eslint": "^8.0.0" }
}'
write_if_missing "$DIR/.eslintrc.json" '{
  "env": { "node": true, "es2021": true },
  "rules": { "no-unused-vars": "error", "no-undef": "error", "eqeqeq": "warn" }
}'
mkdir -p "$DIR/src"
write_if_missing "$DIR/src/index.js" "var unused1 = 1;
var unused2 = 2;
var unused3 = 3;
console.log(unknownVar);
if (x == 1) { console.log('loose'); }
if (y == 2) { console.log('loose'); }
function foo() { return bar; }
function baz() { return qux; }
let a = notDefined;
let b = alsoNotDefined;
let c = stillNotDefined;"
if [ ! -d "$DIR/node_modules" ] && command -v npm &>/dev/null; then
  (cd "$DIR" && npm install --silent 2>/dev/null) || true
fi

# ── 7. test-rust-errors ──────────────────────────────────────────────────
# Used by: cargo-build-errors, build-errors-fix-continuation
DIR="$FIXTURES_DIR/test-rust-errors"
create_if_missing "$DIR"
write_if_missing "$DIR/Cargo.toml" '[package]
name = "test_errors"
version = "0.1.0"
edition = "2021"'
mkdir -p "$DIR/src"
write_if_missing "$DIR/src/main.rs" 'fn main() {
    let x: i32 = "not a number";
    let y = undefined_function();
    println!("{}", x);
}'

# ── 8. test-ts-errors ────────────────────────────────────────────────────
# Used by: tsc-errors
DIR="$FIXTURES_DIR/test-ts-errors"
create_if_missing "$DIR"
write_if_missing "$DIR/tsconfig.json" '{"compilerOptions": {"strict": true, "noEmit": true}}'
write_if_missing "$DIR/app.ts" 'interface User {
    name: string;
    age: number;
}

function greet(user: User): string {
    return "Hello " + user.namee;  // typo: namee
}

const result: number = greet({name: "Alice", age: 30});  // wrong type'

# ── 9. test-make-project ─────────────────────────────────────────────────
# Used by: make-build
DIR="$FIXTURES_DIR/test-make-project"
create_if_missing "$DIR"
write_if_missing "$DIR/Makefile" 'all: hello

hello: hello.c
	gcc -o hello hello.c

clean:
	rm -f hello'
write_if_missing "$DIR/hello.c" '#include <stdio.h>
int main() {
    printf("Hello, world!\n");
    return 0;
}'

# ── 10. Standalone fixture files ─────────────────────────────────────────
# Used by prompts referencing /tmp/lint_issues.py and /tmp/test_eval_fail.py

write_if_missing "$FIXTURES_DIR/lint_issues.py" 'import os
import sys
import json
import re
import collections
import itertools

def process():
    unused_var = 42
    another_unused = "hello"
    x = None
    if x == True:
        pass
    y = None
    if y == False:
        pass

    try:
        open("/dev/null")
    except:
        pass

    return x'

write_if_missing "$FIXTURES_DIR/test_eval_fail.py" 'def add(a, b):
    return a + b

def multiply(a, b):
    return a * b

def divide(a, b):
    return a / b


def test_add_basic():
    assert add(2, 3) == 5

def test_add_negative():
    assert add(-1, 1) == 0

def test_add_zero():
    assert add(0, 0) == 0


def test_multiply_basic():
    assert multiply(2, 3) == 6

def test_multiply_zero():
    assert multiply(5, 0) == 0

def test_multiply_correct():
    # BUG: should be 20, not 21
    assert multiply(4, 5) == 21

def test_divide_basic():
    # BUG: integer vs float
    assert divide(10, 3) == 3

def test_divide_one():
    assert divide(7, 1) == 7


def test_add_large():
    # BUG: overflow-ish assertion
    assert add(999999, 1) == 999999'

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "Bootstrap complete. Fixtures in: $FIXTURES_DIR"
echo ""
echo "Fixture directories:"
ls -1d "$FIXTURES_DIR"/test-* 2>/dev/null | while read -r d; do echo "  $(basename "$d")"; done
echo ""
echo "Standalone files:"
ls -1 "$FIXTURES_DIR"/*.py 2>/dev/null | while read -r f; do echo "  $(basename "$f")"; done
