#!/bin/bash

################################################################################
# StoryMe - Complete Test Suite Runner
#
# This script runs all tests in sequence and provides a summary.
# Ensures all components of the application are working correctly.
################################################################################

set -e  # Exit on any error

echo ""
echo "################################################################################"
echo "#                                                                              #"
echo "#                     STORYME - COMPLETE TEST SUITE                            #"
echo "#                                                                              #"
echo "################################################################################"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# ============================================================================
# Backend Tests
# ============================================================================
echo ""
echo "${BLUE}========================================================================${NC}"
echo "${BLUE}STEP 1: Running Backend API Tests (9 tests)${NC}"
echo "${BLUE}========================================================================${NC}"
echo ""

cd /app/tests/backend

if python test_api_storybook_generation.py; then
    echo ""
    echo "${GREEN}✓ Backend tests PASSED${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 9))
else
    echo ""
    echo "${RED}✗ Backend tests FAILED${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 9))
fi

TOTAL_TESTS=$((TOTAL_TESTS + 9))

# ============================================================================
# Integration Tests
# ============================================================================
echo ""
echo "${BLUE}========================================================================${NC}"
echo "${BLUE}STEP 2: Running Frontend Integration Tests (1 test)${NC}"
echo "${BLUE}========================================================================${NC}"
echo ""

cd /app/tests/integration

if python test_frontend_download.py; then
    echo ""
    echo "${GREEN}✓ Integration tests PASSED${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo ""
    echo "${RED}✗ Integration tests FAILED${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi

TOTAL_TESTS=$((TOTAL_TESTS + 1))

# ============================================================================
# Final Summary
# ============================================================================
echo ""
echo "################################################################################"
echo "#                                                                              #"
echo "#                           FINAL TEST SUMMARY                                 #"
echo "#                                                                              #"
echo "################################################################################"
echo ""
echo "  Total Tests: $TOTAL_TESTS"
echo "  ${GREEN}✓ Passed: $PASSED_TESTS${NC}"

if [ $FAILED_TESTS -gt 0 ]; then
    echo "  ${RED}✗ Failed: $FAILED_TESTS${NC}"
    echo ""
    echo "  ${RED}Success Rate: $(awk "BEGIN {printf \"%.1f\", ($PASSED_TESTS/$TOTAL_TESTS)*100}")%${NC}"
    echo ""
    echo "################################################################################"
    echo ""
    echo "${RED}❌ SOME TESTS FAILED${NC}"
    echo ""
    exit 1
else
    echo "  ${GREEN}✗ Failed: 0${NC}"
    echo ""
    echo "  ${GREEN}Success Rate: 100.0%${NC}"
    echo ""
    echo "################################################################################"
    echo ""
    echo "${GREEN}🎉 ALL TESTS PASSED! 🎉${NC}"
    echo ""
    echo "Test outputs saved to: /app/tests/test_output/"
    echo ""
    exit 0
fi
