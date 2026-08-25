import pyspark
print(101)
spark = pyspark.SparkSession.builder.appName("CustomApp").getOrCreate()
spark.sql("SELECT * FROM spark_table").show()
print(102)
spark.sql("SELECT id  FROM spark_table").show()