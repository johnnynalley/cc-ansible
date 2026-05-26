# Logging Templates

## Templates

- `alloy-config.alloy.j2`: Grafana Alloy log shipping configuration.

## Consumers

- `playbooks/logging.yml`

## Safety Notes

- This template is rendered for multiple OS families. Check Linux and macOS
  paths before changing scrape targets or labels.
