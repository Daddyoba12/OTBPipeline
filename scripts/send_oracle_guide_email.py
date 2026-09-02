import requests

RESEND_KEY = 're_NBmq2tLE_5okoCJwYhdZFtJmVt7GC5U85'

html = (
    "<h2>BootHop Oracle Cloud &mdash; New London Server</h2>"
    "<p>Your new paid Oracle instance is fully set up and running.</p>"
    "<table border='1' cellpadding='8' cellspacing='0' style='border-collapse:collapse;font-family:monospace'>"
    "<tr><td><b>IP Address</b></td><td>130.162.162.189</td></tr>"
    "<tr><td><b>Region</b></td><td>UK South (London)</td></tr>"
    "<tr><td><b>Shape</b></td><td>VM.Standard.E4.Flex &mdash; 2 OCPUs, 16 GB RAM</td></tr>"
    "<tr><td><b>OS</b></td><td>Ubuntu 22.04 LTS</td></tr>"
    "<tr><td><b>Pipeline path</b></td><td>/opt/otb_pipeline</td></tr>"
    "</table>"

    "<h3>SSH Command</h3>"
    "<pre style='background:#f4f4f4;padding:12px'>"
    "ssh -i oracle_boothop.pem ubuntu@130.162.162.189"
    "</pre>"

    "<h3>What's Running</h3>"
    "<ul>"
    "<li>Telegram Commander &mdash; active (systemd, auto-restarts on reboot)</li>"
    "<li>8 cron jobs scheduled (pipeline slots 1-4, engage bot, weekly review, SEO report, follower tracker)</li>"
    "<li>All API keys copied (keys.env)</li>"
    "<li>Social credentials copied (social_credentials.json)</li>"
    "</ul>"

    "<h3>Cron Schedule (UTC)</h3>"
    "<table border='1' cellpadding='8' cellspacing='0' style='border-collapse:collapse'>"
    "<tr><th>Time</th><th>Job</th></tr>"
    "<tr><td>08:00 daily</td><td>Pipeline Slot 1 (TikTok + IG + YouTube)</td></tr>"
    "<tr><td>14:00 daily</td><td>Pipeline Slot 2</td></tr>"
    "<tr><td>21:00 daily</td><td>Pipeline Slot 3</td></tr>"
    "<tr><td>08:00 Tue+Fri</td><td>Pipeline Slot 4 (LinkedIn + Blog)</td></tr>"
    "<tr><td>Every 2h</td><td>Engagement bot</td></tr>"
    "<tr><td>Mon 05:30</td><td>Weekly review</td></tr>"
    "<tr><td>Mon 08:05</td><td>SEO report (Telegram)</td></tr>"
    "<tr><td>09:00 daily</td><td>Follower tracker</td></tr>"
    "</table>"

    "<h3>Key Commands (run on Oracle via SSH)</h3>"
    "<pre style='background:#f4f4f4;padding:12px'>"
    "# Check commander\n"
    "sudo systemctl status otb-commander\n\n"
    "# Live pipeline log\n"
    "tail -f /home/ubuntu/otb_pipeline.log\n\n"
    "# Manual slot run\n"
    "cd /opt/otb_pipeline &amp;&amp; python3 pipeline.py --slot 1 --force\n\n"
    "# Pull latest code + restart commander\n"
    "git pull &amp;&amp; sudo systemctl restart otb-commander"
    "</pre>"

    "<h3>OCI Console</h3>"
    "<p>cloud.oracle.com &rarr; Compute &rarr; Instances &rarr; <b>boothop-pipeline</b></p>"
    "<p>Instance OCID:<br>"
    "<code>ocid1.instance.oc1.uk-london-1.anwgiljtrja3d2acox25y3wgnxpvpeu3rojkh4igmclddteyzxpuzoklcztq</code></p>"

    "<h3>What Changed from Old Server</h3>"
    "<table border='1' cellpadding='8' cellspacing='0' style='border-collapse:collapse'>"
    "<tr><th></th><th>Old (Amsterdam)</th><th>New (London)</th></tr>"
    "<tr><td>Plan</td><td>Free Tier</td><td>Paid</td></tr>"
    "<tr><td>IP</td><td>140.238.73.32</td><td><b>130.162.162.189</b></td></tr>"
    "<tr><td>Region</td><td>Netherlands</td><td>UK South (London)</td></tr>"
    "<tr><td>Status</td><td>Terminated</td><td>Running</td></tr>"
    "</table>"

    "<hr><p style='color:#888;font-size:12px'>"
    "Full guide: OTB_Pipeline/docs/ORACLE_LONDON_SETUP.md</p>"
)

r = requests.post(
    'https://api.resend.com/emails',
    headers={'Authorization': f'Bearer {RESEND_KEY}', 'Content-Type': 'application/json'},
    json={
        'from': 'BootHop Pipeline <info@boothop.com>',
        'to': ['titobalo12@gmail.com'],
        'subject': 'Oracle London Server Setup Complete | 130.162.162.189',
        'html': html,
    }
)
print('Status:', r.status_code)
print(r.json())
