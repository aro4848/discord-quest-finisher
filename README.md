# discord-quest-finisher

automates discord video quests and 15-minute game quests to claim rewards.

connects directly to the gateway with curl_cffi and simulates real cdn chunk buffering so it runs headless without having discord open.

"disclaimer: for testing only. botting quests is against discord rules. use an alt."

### install

pip install -r requirements.txt

### config

copy your token into `config.json`:
{
  "token": "your_token_here"
}

### run

python main.py
