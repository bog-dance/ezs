# EZS

**ECS, but easy** — Interactive TUI for connecting to ECS containers via AWS SSM Session Manager.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)

## Features

- Multi-region cluster view with keyboard navigation
- Auto-discovery of ECS clusters, services, and tasks
- Smart container selection (excludes ecs-agent)
- Secure connection via SSM (no open ports required)
- SSH to host or docker exec into container
- Live logs streaming (coming soon)
- Beautiful TUI with loading animations

## Demo

```
┌─ EU West (eu-west-1) ─────────────────┐
│ production-cluster                    │
│ staging-cluster                       │
└───────────────────────────────────────┘
┌─ US East (us-east-1) ─────────────────┐
│ api-cluster                           │
│ workers-cluster                       │
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
           "ecs:ListServices",
           "ecs:ListTasks",
           "ecs:DescribeTasks",
           "ecs:DescribeContainerInstances",
           "ssm:StartSession",
           "ssm:DescribeInstanceInformation",
           "ec2:DescribeInstances"
         ],
         "Resource": "*"
       }
     ]
   }
   ```

4. **ECS Container Instances** must have:
   - SSM Agent installed and running
   - IAM role with `AmazonSSMManagedInstanceCore` policy

## Usage

```bash
ezs
```

With AWS profile:
```bash
ezs --profile production
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate up/down |
| `←` / `Escape` | Go back |
| `→` / `Enter` | Select |
| `F1` | Show help |
| `Ctrl+C` | Exit |
| Type | Filter items |

### Workflow

1. **Select Cluster** — Browse clusters grouped by region
2. **Select Service** — Filter and pick a service
3. **Select Task** — Auto-selects if only one running task
4. **Select Container** — Auto-selects if only one container (excludes ecs-agent)
5. **Choose Action**:
   - **SSH → Container** — Docker exec into the container
   - **SSH → Host** — SSH session on the EC2 instance
   - **Logs → Live** — Stream live logs (coming soon)
   - **Logs → Recent** — View recent logs (coming soon)

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

## Architecture

```
ecs_connect/
├── config.py         # Constants (regions)
├── aws_client.py     # AWS API wrappers
├── interactive.py    # Textual TUI
├── ssm_session.py    # SSM session logic
└── main.py           # Entry point
```

## Limitations

- EC2 launch type only (Fargate not yet supported)
- Requires Docker on EC2 instances for container exec
- Only connects to RUNNING tasks

## Roadmap

- [ ] Live logs streaming
- [ ] Fargate support
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
