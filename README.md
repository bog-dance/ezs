# ECS Connect

Інтерактивна CLI-тула для підключення до ECS контейнерів через AWS SSM Session Manager.

## Можливості

- 🌍 Вибір регіону (eu-west-1, eu-west-2, us-east-1)
- 📦 Автоматичне визначення ECS кластерів, сервісів, тасків
- 🎯 Інтелектуальний вибір контейнерів (виключає ecs-agent)
- 🔐 Безпечне підключення через SSM (без відкритих портів)
- 💻 SSH до хоста або docker exec до контейнера

## Вимоги

### AWS

1. **AWS CLI** встановлений і налаштований
   ```bash
   aws --version
   ```

2. **SSM Session Manager Plugin** встановлений
   ```bash
   session-manager-plugin
   ```
   
   Встановлення: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html

3. **AWS Credentials** налаштовані в `~/.aws/credentials`

4. **IAM дозволи**:
   - `ecs:ListClusters`
   - `ecs:ListServices`
   - `ecs:ListTasks`
   - `ecs:DescribeTasks`
   - `ecs:DescribeContainerInstances`
   - `ssm:StartSession`
   - `ssm:SendCommand`
   - `ssm:GetCommandInvocation`
   - `ssm:DescribeInstanceInformation`

5. **ECS Container Instances** повинні мати:
   - SSM Agent встановлений і запущений
   - IAM роль з `AmazonSSMManagedInstanceCore` policy

### Python

- Python 3.8+
- pip

## Встановлення

```bash
# Клонувати або скопіювати проєкт
cd ecs-connect

# Встановити залежності
pip install -r requirements.txt

# Встановити тулу
pip install -e .
```

## Використання

```bash
ecs-connect
```

### Workflow

1. **Вибір регіону** → Dropdown з 3 регіонів
2. **Вибір ECS кластера** → Автоматично завантажує список
3. **Вибір сервісу** → Список сервісів у кластері
4. **Вибір таску** → Автовибір якщо 1, dropdown якщо більше
5. **Визначення контейнера** → Виключає ecs-agent, автовибір якщо 1
6. **Підключення**:
   - `Yes` → Docker exec bash всередині контейнера
   - `No` → SSH сесія на хості

## Troubleshooting

### "Session Manager Plugin not found"

```bash
# macOS
brew install --cask session-manager-plugin

# Linux
curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb"
sudo dpkg -i session-manager-plugin.deb
```

### "Instance not accessible via SSM"

Перевір:
1. SSM Agent запущений на EC2 (`sudo systemctl status amazon-ssm-agent`)
2. IAM роль інстансу має `AmazonSSMManagedInstanceCore`
3. Security group дозволяє outbound HTTPS (443) до AWS endpoints

### "No running tasks found"

- Перевір статус сервісу: `aws ecs describe-services --cluster <cluster> --services <service>`
- Подивись логи тасків у AWS Console

## Архітектура

```
ecs_connect/
├── config.py         # Константи (регіони)
├── aws_client.py     # Boto3 обгортки
├── interactive.py    # Questionary меню
├── ssm_session.py    # SSM логіка
└── main.py           # Entry point
```

## Обмеження

- Працює тільки з ECS тасками у статусі RUNNING
- Потребує Docker на EC2 інстансах (для exec в контейнер)
- Не підтримує Fargate (тільки EC2 launch type)

## TODO

- [ ] Підтримка AWS профілів через CLI аргумент
- [ ] Кешування списку кластерів
- [ ] Підтримка custom shell (zsh, fish)
- [ ] Логування сесій
- [ ] Batch підключення до декількох контейнерів

## Ліцензія

MIT
