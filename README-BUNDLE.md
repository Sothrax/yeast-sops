# yeast-sops bundle — content

Tenhle balík obsahuje tři věci:

## 1. `yeast-sops/` — obsah Git repa
Připravené k pushi na `git@github.com:Sothrax/yeast-sops.git`.

Setup:
```bash
cd yeast-sops
git init
git remote add origin git@github.com:Sothrax/yeast-sops.git
pip install pyyaml jsonschema
python scripts/validate.py          # mělo by projít čistě
git add .
git commit -m "Initial scaffold: schemas, templates, scripts, seed SOP"
git push -u origin main
```

## 2. `claude-skills/` — pět Claude Code skillů
Nakopíruj do `~/.claude/skills/`:

```bash
cp -r claude-skills/* ~/.claude/skills/
```

Skilly:
- `sop-shared` — shared base, ostatní skilly ho referencují
- `sop-create` — interview-driven creation
- `sop-refine` — diff-based editing
- `sop-validate` — wrapper kolem validate.py
- `sop-role` — bundle SOPek do role YAML
- `sop-to-agent` — compile SOP → Cortex agent YAML

## 3. `yeast-sops-project-prompt.md` — Claude Project system prompt
Zkopíruj obsah do Claude.ai projektu "yeast-sops" jako system prompt,
nebo nastav v Cowork jako project instructions. Stejný prompt funguje
v Claude Code / Cowork i bez formálních skillů — stačí, aby Claude
měl přístup k repu.

## End-to-end test (ověřeno)

```bash
# 1. Validace projde čistě
python scripts/validate.py
# → Checked 3 files: 0 errors, 0 warnings

# 2. Instantiate template pro taf-estate (už je předvyrobeno, můžeš smazat a zkusit znova)
rm -rf instances/taf-estate
cat > /tmp/params.yaml <<'PARAMS'
bank_account_iban: "CZ65 0300 0000 0001 2345 6789"
company_flexibee_code: "TAF_ESTATE_SRO"
notification_channel: "slack:#taf-accounting"
unmatched_threshold_czk: 10000
PARAMS
python scripts/instantiate.py \
    --template SOP-ACC-T001 \
    --tenant taf-estate \
    --instance-id SOP-ACC-I001 \
    --params /tmp/params.yaml
# → Created: instances/taf-estate/accounting/SOP-ACC-I001-bank-reconciliation-csob.md

# 3. Compile do Cortex agent YAML
python scripts/to_agent.py --sop SOP-ACC-I001
# → 37 řádků validního YAML, ready for Cortex
```

Všechno v tomhle balíku je produkčně použitelné, otestované end-to-end.
