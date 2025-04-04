# start by pulling the python image
FROM python:3.13

# Install setuptools
RUN pip install setuptools

# Install UWSGI
RUN pip install uwsgi

# copy the requirements file into the image
COPY ./requirements.txt /app/requirements.txt

# switch working directory
WORKDIR /app

# install the dependencies and packages in the requirements file
RUN pip install -r requirements.txt

# copy content from the local file to the image
COPY --chown=www-data:www-data . /app

# expose the port for flask
EXPOSE 5000

# set the flask env variable
ENV FLASK_APP=md-publisher.py
ENV MD_PUBLISHER_ROOT=.

# Set the user as www-data
USER www-data

# run uwsgi
CMD ["uwsgi", "--http", ":5000", "--wsgi-file", "md-publisher.wsgi"]