pkill -f "gunicorn.*app:app"
sleep 2
nohup gunicorn -w 4 -b 127.0.0.1:5000 app:app > gunicorn.log 2>&1 &
