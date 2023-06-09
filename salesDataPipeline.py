# -*- coding: utf-8 -*-


## File descriptions
- **sales_train.csv** - the training set. Daily historical data from January 2013 to October 2015.
- **test.csv** - the test set. 
- **items.csv** - supplemental information about the items/products.
- **item_categories.csv**  - supplemental information about the items categories.
- **shops.csv** - supplemental information about the shops.

## Data fields
- **ID** - an Id that represents a (Shop, Item) tuple within the test set
- **shop_id** - unique identifier of a shop
- **item_id** - unique identifier of a product
- **item_category_id** - unique identifier of item category
- **item_cnt_day** - number of products sold.
- **item_price** - current price of an item
- **date** - date in format dd/mm/yyyy
- **date_block_num** - a consecutive month number, used for convenience. January 2013 is 0, February 2013 is 1,..., October 2015 is 33
- **item_name** - name of item
- **shop_name** - name of shop
- **item_category_name** - name of item category

# Libraries
"""

!pip install findspark
!pip install pyspark

import findspark
findspark.init()

import warnings
warnings.filterwarnings('ignore')

from pyspark.sql import SparkSession, Window

from pyspark.sql.functions import *
from pyspark.ml.feature import OneHotEncoder, VectorAssembler, StringIndexer

from pyspark.ml import Pipeline
from pyspark.sql import functions as f

from pyspark.ml.regression import GBTRegressor, LinearRegression, RandomForestRegressor

from pyspark.ml.evaluation import RegressionEvaluator

"""# Create spark session"""

spark = SparkSession \
    .builder \
    .appName("Predict future sales") \
    .config("spark.ui.showConsoleProgress", "false") \
    .config("spark.driver.memory", "12g") \
    .getOrCreate()
spark.sparkContext.uiWebUrl

"""# Read data

### Main file
"""

df = spark.read.csv('sample_data/sales_train.csv', header=True, inferSchema=True)
df = df.withColumn('date',to_date(df.date,'dd.MM.yyyy'))

df.show(3)
df.printSchema()
print("Count:",df.count())

"""### Items"""

items = spark.read.csv('sample_data/items.csv',header=True)

items.show(3,truncate=False)
items.printSchema()
print('Count:',items.count())

"""### Categories"""

categories = spark.read.csv('sample_data/item_categories.csv',header=True)

categories.show(3,truncate=False)
categories.printSchema()
print('Count:',categories.count())

"""### Shops"""

shops = spark.read.csv('sample_data/shops.csv',header=True)
shops.show(5)
shops.printSchema()

test = spark.read.csv('sample_data/test.csv',header=True)
test.show(5)
test.printSchema()

# Replace timestamp with separate columns for month and year
df = df.withColumn("date",f.to_timestamp(df.date, 'dd.MM.yyyy'))
df = df.withColumn("year",f.year(df.date))
df = df.withColumn("month",f.month(df.date))
df.show()

# Instead of daily sale numbers, replace with sales per month

print(f"Number of records in the train set before the monthly grouping: {df.count()}")
col = ["date_block_num","year","month","shop_id","item_id"]
df = df.groupby(col).sum("item_cnt_day")\
             .select(col + [f.col("sum(item_cnt_day)").alias("item_cnt_month")])
print(f"Number of records in train set after the monthly grouping: {df.count()}")
df.show()

# Remove rows with NULL value for "shop_id"
a = shops.filter(shops.shop_id.cast("int").isNull()).toPandas()

# Find the number of unique items in training and test data
print(f"Number of unique items in Train dataset: {df.select('item_id').distinct().count()}")
items_for_pred = [i[0] for i in test.select("item_id").distinct().collect()]
print(f"Number of unique items in Test dataset: {len(items_for_pred)}")
print(f"Filtering the train set & items set with such items ...")

# In the training set, Keep only the items which need to be predicted
print(f"Length of train set [{df.count()}] rec. -----> ", end="")
df = df.filter(df.item_id.isin(items_for_pred))
print(f"[{df.count()}] rec.")

# In the items set, Keep only the items which need to be predicted
print(f"Length of items set [{items.count()}] rec. -----> ", end="")
items = items.filter(items.item_id.isin(items_for_pred))
print(f"[{items.count()}] rec.")

# Find Number of unique shops in Train dataset and Keep only the shops which need to be predicted

print(f"Number of unique shops in Train dataset: {df.select('shop_id').distinct().count()}")
shops_for_pred = [i[0] for i in test.select("shop_id").distinct().collect()]
print(f"Number of unique shops in Test dataset: {len(shops_for_pred)}")
print(f"Filtering the train set & shops set with such items ...")

print(f"Length of train set [{df.count()}] rec. -----> ", end="")
df = df.filter(df.shop_id.isin(shops_for_pred))
print(f"[{df.count()}] rec.")

print(f"Length of items set [{shops.count()}] rec. -----> ", end="")
shops = shops.filter(shops.shop_id.isin(shops_for_pred))
print(f"[{shops.count()}] rec.")

# Create a temporary dataset "allComb" by selecting shops, items for each month

_shops = df.select("shop_id").distinct()
_items = df.select("item_id").distinct()
_blocks = df.select(["date_block_num","year","month"]).distinct()
allcomb = _shops.crossJoin(_items).crossJoin(_blocks)
print(f"The len of the dataset should be equel to {allcomb.count()}") 
print("to consider all combinations of shop_id & item_id for each month")

# Create all combinations of shop_id & item_id for each month in the training set

df = \
allcomb.join(df.alias("t"),(allcomb.item_id == f.col("t.item_id")) & 
                              (allcomb.shop_id == f.col("t.shop_id")) & 
                              (allcomb.date_block_num == f.col("t.date_block_num")),"left")\
       .select([allcomb.item_id,allcomb.shop_id,allcomb.date_block_num,allcomb.month,
                allcomb.year, f.col("t.item_cnt_month")])
       
# Fill "NA" item count values with 0
df = df.na.fill({'item_cnt_month': 0})
print(f"[{df.count()}] rec.2")

# Since does not have date information, make 11.2015 as the month of the test set

N,Y,M = 34, 2015, 11

test = test.withColumn("date_block_num", f.lit(N))\
           .withColumn("year", f.lit(Y))\
           .withColumn("month", f.lit(M))\
           .withColumn("item_cnt_month", f.lit(None))\
           .drop("ID")

# Combine train and test data

df = df.union(test.select(["item_id","shop_id","date_block_num","year","month","item_cnt_month"]))
test.show()

df.show()

# Find correlation between date_block_num and sales per month
df.stat.corr("date_block_num", "item_cnt_month")

df.stat.corr("month", "item_cnt_month")

df.stat.corr("year", "item_cnt_month")

!pip install pyspark_dist_explore
from pyspark_dist_explore import hist
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
hist(ax, df.select('month'), bins = 20, color=['red'])

# Scatter plot for "item_cnt_month" to check if it needs normalization
df.toPandas().plot.scatter(x='date_block_num', y='item_cnt_month')

"""# Modeling"""

# Select item_cnt_month as the value to predict for Random forest regression
X = df.toPandas()
X.dropna(inplace=True)

y = X.pop("item_cnt_month")

from sklearn.model_selection import train_test_split

X_train, X_valid, y_train, y_valid = train_test_split(X, y, random_state=0
                                                    , train_size=0.80
                                                    , test_size=0.20)

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.preprocessing import MinMaxScaler
from sklearn.compose import ColumnTransformer
# Creating Numerical Transformer
numerical_transformer = Pipeline(steps=[
    ('scaler', MinMaxScaler())
])
# Bundling Preprocessors
preprocessor = ColumnTransformer(
    transformers=[
        ('numerical', numerical_transformer, X.columns),
    ]
)

from sklearn.ensemble import RandomForestRegressor
# Creating Model
rfg_model = RandomForestRegressor(
    n_estimators=10,
    criterion='squared_error',
    random_state=0,
)

rfg_pipeline = Pipeline(steps=[
    ('preprocessor', preprocessor),
    ('model', rfg_model),
])

# Training and Predicting
rfg_pipeline.fit(X_train, y_train)
print('Training: Done!')
rfg_predictions = rfg_pipeline.predict(X_valid)
print('Predictions: Done!')

from sklearn.metrics import mean_squared_error # add 'sqrt' to calculate RMSE

# Calculating RMSE
from math import sqrt
rfg_rmse = np.sqrt(mean_squared_error(rfg_predictions, y_valid))
print('RFG RMSE:', rfg_rmse)