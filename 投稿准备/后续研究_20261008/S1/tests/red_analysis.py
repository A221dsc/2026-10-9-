"""Deliberately wrong, executable test-only negative controls. Never production."""
import math

def two_round_ratio(values):
    return sum(c / r for r, c in values) / 2  # deliberately arithmetic

def classify(logs, lower, upper, floor=0):
    return 'strong_fast' if min(logs) < math.log(.95) else 'unresolved'

def choose(candidates):
    return min(candidates, key=lambda row: row['online'])['method']

def accept_pair(pair):
    return all(row['status'] == 'valid' for row in pair['raw'])  # ignores sidecars
