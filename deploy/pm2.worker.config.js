module.exports = {
  apps: [
    {
      name: "moltgrid-worker",
      script: "moltgrid-worker.py",
      interpreter: "python3",
      cwd: "/opt/moltgrid",
      env: {
        MOLTGRID_API_URL: "https://api.moltgrid.net",
        MOLTGRID_POLL_INTERVAL: "30"
      },
      autorestart: true,
      watch: false,
      max_restarts: 10,
      restart_delay: 10000,
      log_date_format: "YYYY-MM-DD HH:mm:ss"
    }
  ]
};
