# EZS

**ECS, but easy** — Interactive TUI for AWS ECS container management via SSM Session Manager.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)

## Features

- **Multi-region cluster navigation** — Browse ECS clusters across all AWS regions with keyboard navigation
- **Auto-discovery** — Automatic detection of clusters, services, tasks, and containers
- **Secure connection** — SSH via SSM Session Manager (no open ports required)
- **Container access** — Docker exec into containers or SSH to EC2 hosts
- **Live logs streaming** — Real-time CloudWatch logs with level filtering
- **Log download** — Download logs from last 5 minutes to 24 hours
- **Environment variables** — View, edit env vars, SSM parameters, and Secrets Manager values
- **Service redeployment** — Force redeploy one or multiple services
- **Smart caching** — Fast navigation with parallel data prefetching
- **Beautiful TUI** — Dark theme with loading animations

## Demo

```
┌─ EU West (eu-west-1) ─────────────────┐
│ ▸ production-cluster                  │
│   staging-cluster                     │
└───────────────────────────────────────┘
┌─ US East (us-east-1) ─────────────────┐
│   api-cluster                         │
│   workers-cluster                     │
└───────────────────────────────────────┘
```

## Installation

```bash
pip install ezs
```

Or install from source:

```bash
git clone https://github.com/yourusername/ezs.git
cd ezs
pip install -e .
```

## Requirements

### AWS

1. **AWS CLI** configured with credentials
   ```bash
   aws configure
   ```

2. **SSM Session Manager Plugin** installed
   ```bash
   # macOS
   brew install --cask session-manager-plugin

   # Linux (Debian/Ubuntu)
   curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb"
   sudo dpkg -i session-manager-plugin.deb
   ```

3. **IAM Permissions**:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "ecs:ListClusters",
           "ecs:DescribeClusters",
           "ecs:ListServices",
           "ecs:DescribeServices",
           "ecs:ListTasks",
           "ecs:DescribeTasks",
           "ecs:DescribeTaskDefinition",
           "ecs:DescribeContainerInstances",
           "ecs:RegisterTaskDefinition",
           "ecs:UpdateService",
           "ssm:StartSession",
           "ssm:DescribeInstanceInformation",
           "ssm:GetParameters",
           "ec2:DescribeInstances",
           "logs:GetLogEvents",
           "logs:DescribeLogStreams",
           "secretsmanager:GetSecretValue"
         ],
         "Resource": "*"
       }
     ]
   }
   ```

4. **ECS Container Instances** must have:
   - SSM Agent installed and running
   - IAM role with `AmazonSSMManagedInstanceCore` policy
   - Outbound HTTPS (443) access to AWS endpoints
   - Docker installed (for container exec)

## Usage

```bash
ezs
```

With AWS profile:
```bash
ezs --profile production
```

Re-configure regions:
```bash
ezs --configure
```

### First Run Setup

On first launch, EZS will guide you through region configuration:

1. **Auto-Detect** — Scans all AWS regions to find those with ECS clusters (1-2 minutes)
2. **Manual Selection** — Choose specific regions from the list

Configuration is saved to `~/.config/ezs/config.yaml`.

## Navigation

### Workflow

1. **Select Cluster** — Browse clusters grouped by region
2. **Select Service** — Filter and pick a service
3. **Select Task** — View task details (IP, instance ID, start time)
4. **Task Menu** — For multi-container tasks, choose container or view all logs
5. **Select Action** — Choose what to do with the container

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate up/down |
| `←` / `Escape` | Go back |
| `→` / `Enter` | Select |
| `Tab` / `Shift+Tab` | Switch sections |
| `F1` | Show help |
| `Ctrl+C` / `Ctrl+D` | Exit |
| Type | Filter items |

### Service Screen Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+U` | Force redeploy services |

### Live Logs Shortcuts

| Key | Action |
|-----|--------|
| `A` | Show all log levels |
| `E` | Show only ERROR |
| `W` | Show only WARNING |
| `I` | Show only INFO |
| `D` | Show only DEBUG |
| `1-9` | Filter by container (multi-container tasks) |
| `Q` | Exit logs |

### Modal Shortcuts

| Key | Action |
|-----|--------|
| `Space` | Toggle selection |
| `A` | Select/deselect all |
| `Y` / `N` | Quick yes/no |

## Features in Detail

### SSH Access

- **Container** — Docker exec into the selected container via SSM
- **Host** — SSH to the EC2 instance running the container

EZS uses SSM Session Manager, so no open ports or SSH keys are required.

### Live Logs

Stream CloudWatch logs in real-time with filtering capabilities:

- Filter by log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Filter by container in multi-container tasks
- Color-coded container prefixes
- Auto-scrolling with new events

### Download Logs

Download logs for a specified time range:

- Last 5, 15, 30 minutes
- Last 1, 2, 6, 12, 24 hours
- Saves to `~/Downloads/` with timestamped filename
- Shows log statistics by level

### Environment Variables

View and manage container configuration:

- **Regular env vars** — Plain text values
- **SSM Parameters** — Fetched values, `[SECURE]` for SecureString
- **Secrets Manager** — Fetched values, `[SECRET]` marker
- **Edit & Deploy** — Modify values and redeploy the service
- **Copy with masking** — Copy env vars while masking secrets

### Service Redeployment

Force redeploy services without changing configuration:

- Press `Ctrl+U` in the service selection screen
- Select one or multiple services
- Watch progress as services are redeployed

## Architecture

```
ezs/
├── main.py              # Entry point and CLI
├── interactive.py       # Main TUI application
├── aws_client.py        # AWS API wrapper
├── config.py            # Constants and regions
├── config_manager.py    # Configuration file handling
├── setup_wizard.py      # First-run setup
├── ssm_session.py       # SSM session management
├── live_logs.py         # Live logs viewer
├── download_logs.py     # Log download functionality
└── env_viewer.py        # Environment variables viewer/editor
```

## Troubleshooting

### "Session Manager Plugin not found"

Install the plugin:
```bash
# macOS
brew install --cask session-manager-plugin

# Verify installation
session-manager-plugin
```

### "Instance not accessible via SSM"

1. Check SSM Agent is running: `sudo systemctl status amazon-ssm-agent`
2. Verify IAM role has `AmazonSSMManagedInstanceCore` policy
3. Ensure security group allows outbound HTTPS (443) to AWS endpoints

### "No running tasks found"

- Check service status: `aws ecs describe-services --cluster <cluster> --services <service>`
- Verify tasks are in RUNNING state in AWS Console

### "No clusters found"

Run `ezs --configure` to detect regions with ECS clusters or manually select regions.

## Limitations

- EC2 launch type only (Fargate support is partial)
- Requires Docker on EC2 instances for container exec
- Only connects to RUNNING tasks
- Single AWS profile at a time

## Roadmap

- [ ] Full Fargate support
- [ ] Custom shell selection (zsh, fish)
- [ ] Session logging
- [ ] Favorites/bookmarks
- [ ] Port forwarding

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License - see [LICENSE](LICENSE) for details.
