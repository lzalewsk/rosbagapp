FROM ros:melodic
MAINTAINER Lukasz Zalewski <lzalewsk@gmail.com>

# Get and install required packages.
RUN apt-get update && apt-get install -y -q \
    python-pip \
#    build-essential \
#    python-dev \
#    python-pip \
#    libpq-dev \
     && rm -rf /var/lib/apt/lists/*

# Install required dependencies (includes Flask and uWSGI)
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Create a place to deploy the application
ENV APP_DIR /app
RUN mkdir -p $APP_DIR
WORKDIR $APP_DIR

# Set default ENV
COPY . $APP_DIR/
RUN echo "source /opt/ros/melodic/setup.bash" >> /root/.bashrc 

# Expose the port where uWSGI will run
EXPOSE 5000

# Run server
CMD exec gunicorn --bind 0.0.0.0:5000 app:app --workers 3
