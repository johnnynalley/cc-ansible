# apps Playbooks

Owner area: Standalone application appliances.

## Operating Notes

- Key vars: freepbx_*, apt_pin_release.
- Template owners: templates/freepbx.
- Script owners: none by default.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `freepbx.yml` | `freepbx-vm` | Configure FreePBX/Asterisk guardrails. | `ansible-playbook playbooks/apps/freepbx.yml --syntax-check` |
| `homebridge.yml` | `homebridge-lxc` | Configure Homebridge appliance guardrails. | `ansible-playbook playbooks/apps/homebridge.yml --syntax-check` |
