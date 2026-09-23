"""Historical schema comparisons retain the old chain constraints explicitly."""
def before_mc1(signature):
    old={'ck_attribution_claims_2':"chain IN ('bitcoin','ethereum')",
         'ck_discovery_subjects_6':"kind != 'blockchain_address' OR namespace IN ('bitcoin','ethereum')"}
    return {**signature,'checks':[(name,old.get(name,sql)) for name,sql in signature['checks']]}
