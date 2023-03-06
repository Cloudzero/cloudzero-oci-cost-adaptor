FROM public.ecr.aws/lambda/python:3.9

COPY requirements.txt . 
RUN pip3 install -r requirements.txt --target ${LAMBDA_TASK_ROOT}

COPY lambda.py ${LAMBDA_TASK_ROOT}
COPY anycostoci.py ${LAMBDA_TASK_ROOT}

CMD ["lambda.anycost"]

