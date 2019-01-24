"""
=================================================
Imputing missing values using multiple imputation
=================================================

By default, the `sklearn.impute.IterativeImputer` performs single imputation:
a method where every missing value is replaced with one imputed value.
The chained character of the method and the possibility to draw imputation
values from the posterior distribution of a Bayesian imputation model allows
for the finding of unbiased statistical estimates. However, the disadvantage is
that every imputed value is treated as if the value was observed, leading to an
imputed dataset that does not reflect the uncertainty that occurs due to the
presence of missing values. This makes it hard to find valid statistical
inferences because the variance (and standard error) of statistical estimates
become too small.

An alternative is using the `sklearn.impute.IterativeImputer` to perform
multiple imputation: a method where every missing value is imputed multiple
times. The procedure results in multiple datasets where the observed data is
identical in every dataset, but the imputed data is different.
All desired steps after imputation are performed on every dataset, such as
standardization, feature engineering and model fitting.

One final model is obtained by combining the estimates of each model with
Rubin's pooling rules. These rules assume that the parameters of interest are
normally distributed which is the case with, for example, estimates of the mean
and regression coefficients. Other parameters, such as correlation
coefficients need transformation to suit the assumption of normality.
If it is not possible to approximate a normal distribution, it is better to use
robust summary measures such as medians or ranges instead of using Rubin's
pooling rules. This applies to an estimate like explained variance.

In sum, Rubin's pooling rules are as follows. The overall point estimate after
multiple imputation (denoted by Qbar) is the average of all the m point
estimates. The variance of the overall point estimate is a combination of
so-called within imputation variance (Ubar) and between imputation
variance (B). Ubar is the average of the m variances of the m point estimates.
Both Qbar and Ubar are corrected with a factor 1 / m to account for sampling
variance. The between imputation variance (B) is the sum of the squared
difference between Qbar and the m point estimates, corrected with a factor
1 / (m – 1). Then, the total variance (T) of the MI overall point estimate is
Ubar + B + B/m.

In this Example we will show how to use the `sklearn.impute.IterativeImputer`
to perform multiple imputation. In Example 1 we show the effect of Rubin’s
pooling rules on the variance of regression estimates. Due to the between
imputation variance, the standard errors of all regression coefficients are
larger with multiple imputation than with single imputation.

In Example 2 we show how to set up a prediction model using multiple
imputation. We combine the predictions from multiple imputations and show that
this results in better regression performance.

# Authors: Rianne Schouten <r.m.schouten@uu.nl>
           Sergey Feldman <sergeyfeldman@gmail.com>
# License: BSD 3 clause
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy import stats

from sklearn.datasets import load_boston
from sklearn.linear_model import RidgeCV
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.impute import IterativeImputer
from sklearn.metrics import mean_squared_error as mse

rng = np.random.RandomState(0)

N_ITER = 20  # number of iterations in IterativeImputer
N_SIM = 3  # number of simulations in Example 2


# Start by defining a basic amputation function
def ampute(X, missing_rate=0.75, mech="MCAR"):
	X_out = X.copy()
	n_drop_per_feature = int(missing_rate * X.shape[0])
	for x in np.transpose(X_out):
	    # insert missing values for each feature
	    if mech == 'MCAR':
	        prob = None
	    else:
	        weights = scipy.special.expit(x - x.mean())
	        prob = weights / weights.sum()
	    drop_idx = np.random.choice(X.shape[0], p=prob, replace=False,
	                                size=n_drop_per_feature)
	    x[drop_idx] = np.nan
	return X_out
    n_samples = X.shape[0]
    n_features = X.shape[1]
    X_incomplete = X.copy()

    n_samples_range = np.arange(n_samples)
    size = int(missing_rate * n_samples)

    # MCAR mechanism
    if mech == 'MCAR':
        for i in np.arange(n_features):
            dropped_indices = np.array(np.random.choice(n_samples_range,
                                                        size=size,
                                                        replace=False))
            X_incomplete[dropped_indices[:, None], i] = None

    # MNAR mechanism
    if mech == "MNAR":
        for i in np.arange(n_features):
            data_values = -np.mean(X[:, i]) + X[:, i]
            weights = 1 / (1 + np.exp(-data_values))
            probs = np.array(weights) / np.sum(np.array(weights))
            dropped_indices = np.array(np.random.choice(n_samples_range,
                                                        size=size,
                                                        p=probs,
                                                        replace=False))
            X_incomplete[dropped_indices[:, None], i] = None

    return X_incomplete


# Make a function that calculates the variance of the beta estimates. This is
# necessary because the linear regression model from sklearn does not provide
# these values.
def calculate_variance_of_beta_estimates(y_true, y_pred, X):
    residuals = np.sum((y_true - y_pred)**2)
    sigma_hat_squared = (1 / (len(y_true) - 2)) * residuals
    X_prime_X = np.dot(X.T, X)
    covariance_matrix = sigma_hat_squared / X_prime_X
    vars = np.diag(covariance_matrix)

    return vars


# Apply Rubin's pooling rules as follows.
# The value of every estimate is the mean of the estimates in each of the m
# datasets (Qbar). The variance of these estimates is a combination of the
# variance of each of the m estimates (Ubar) and the variance between the m
# estimates (B).
#
# Make a function that calculates Qbar from m estimates
def calculate_Qbar(m_estimates):
    m = len(m_estimates)
    Qbar = 1/m * np.sum(m_estimates, axis=0)
    return Qbar


# Make a function that calculates T from m estimates and their variances
def calculate_T(m_estimates, m_variances, Qbar):
    m = len(m_estimates)
    Ubar = 1/m * np.sum(m_variances, axis=0)
    B = 1/(m - 1) * np.sum((Qbar - m_estimates) ** 2, axis=0)
    T = Ubar + B + (B/m)

    return T


###############################################################################

# EXAMPLE 1. COMPARE STATISTICAL ESTIMATES AND THEIR VARIANCE USING MULTIPLE
# IMPUTATION IN A LINEAR REGRESSION MODEL.

###############################################################################


def get_results_full_dataset(X, y):
    # Perform linear regression on full data as a way of comparison
    estimator = RidgeCV()
    estimator.fit(X, y)
    y_predict = estimator.predict(X)

    # Save the beta estimates, the variance of these estimates and 1.96 *
    # standard error of the estimates. The latter is useful to know the 95%
    # confidence interval.
    full_coefs = estimator.coef_
    full_vars = calculate_variance_of_beta_estimates(y, y_predict, X)
    full_errorbar = 1.96 * np.sqrt(full_vars)

    return full_coefs, full_vars, full_errorbar


def get_results_chained_imputation(X_incomplete, y):
    # Impute incomplete data with IterativeImputer using single imputation
    # We perform N_ITER imputations and only use the last imputation.
    imputer = IterativeImputer(n_iter=N_ITER,
                               sample_posterior=True,
                               random_state=0)
    imputer.fit(X_incomplete)
    X_imputed = imputer.transform(X_incomplete)

    # Perform linear regression on chained single imputed data
    # Estimate beta estimates and their variances
    estimator = RidgeCV()
    estimator.fit(X_imputed, y)
    y_predict = estimator.predict(X_imputed)

    # Save the beta estimates, the variance of these estimates and 1.96 *
    # standard error of the estimates
    chained_coefs = estimator.coef_
    chained_vars = calculate_variance_of_beta_estimates(
            y, y_predict, X_imputed)
    chained_errorbar = 1.96 * np.sqrt(chained_vars)

    return chained_coefs, chained_vars, chained_errorbar


def get_results_mice_imputation(X_incomplete, y):
    # Impute incomplete data using the IterativeImputer to perform multiple
    # imputation. We perform N_ITER imputations and only use the last
    # imputation, and loop this procedure m times.
    m = 5
    multiple_imputations = []
    for i in range(m):
        imputer = IterativeImputer(n_iter=N_ITER,
                                   sample_posterior=True,
                                   random_state=i)
        imputer.fit(X_incomplete)
        X_imputed = imputer.transform(X_incomplete)
        multiple_imputations.append(X_imputed)

    # Perform a model on each of the m imputed datasets
    # Estimate the estimates for each model/dataset
    m_coefs = []
    m_vars = []
    for i in range(m):
        estimator = RidgeCV()
        estimator.fit(multiple_imputations[i], y)
        y_predict = estimator.predict(multiple_imputations[i])
        m_coefs.append(estimator.coef_)
        m_vars.append(calculate_variance_of_beta_estimates(
                y, y_predict, multiple_imputations[i]))

    # Calculate the end estimates by applying Rubin's rules.
    Qbar = calculate_Qbar(m_coefs)
    T = calculate_T(m_coefs, m_vars, Qbar)
    mice_errorbar = 1.96 * np.sqrt(T)

    return Qbar, T, mice_errorbar


# The original multiple imputation procedure as developed under the name
# MICE includes all variables in the imputation process; including the output
# variable. The reason to do this is that the imputation model should at least
# contain the analysis model to result in unbiased estimates. In this function,
# we will also include y in the imputation process.
def get_results_mice_imputation_includingy(X_incomplete, y):
    # Impute incomplete data using the IterativeImputer as a MICEImputer
    # Now using the output variable in the imputation loop
    m = 5
    multiple_imputations = []
    for i in range(m):
        Xy = np.column_stack((X_incomplete, y))
        imputer = IterativeImputer(n_iter=N_ITER,
                                   sample_posterior=True,
                                   random_state=i)
        imputer.fit(Xy)
        data_imputed = imputer.transform(Xy)

        # We save only the X imputed data because we do not want to use y to
        # predict y later on.
        X_imputed = data_imputed[:, :-1]
        multiple_imputations.append(X_imputed)

    # Perform linear regression on mice multiple imputed data
    # Estimate beta estimates and their variances
    m_coefs = []
    m_vars = []
    for i in range(m):
        estimator = RidgeCV()
        estimator.fit(multiple_imputations[i], y)
        y_predict = estimator.predict(multiple_imputations[i])
        m_coefs.append(estimator.coef_)
        m_vars.append(calculate_variance_of_beta_estimates(
                y, y_predict, multiple_imputations[i]))

    # Calculate the end estimates by applying Rubin's rules.
    Qbar = calculate_Qbar(m_coefs)
    T = calculate_T(m_coefs, m_vars, Qbar)
    mice_errorbar = 1.96 * np.sqrt(T)

    return Qbar, T, mice_errorbar


# Now lets run all these imputation procedures.
# We use the Boston dataset and analyze the outcomes of the beta coefficients
# and their standard errors. We standardize the data before running the
# procedure to be able to compare the coefficients. We run the procedure for
# MCAR missingness only.
#
# Loading the data
dataset = load_boston()
X_full, y = dataset.data, dataset.target

# Standardizing the data
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_full)
y_scaled = stats.zscore(y)

# Start the procedure
print("Executing Example 1 MCAR Missingness...")

# First, make the data incomplete with a MCAR mechanism.
X_incomplete = ampute(X_scaled, mech="MCAR")

# Second, run all the imputation procedures as described above.
full_coefs, full_vars, full_errorbar = get_results_full_dataset(
        X_scaled, y_scaled)
chained_coefs, chained_vars, chained_errorbar = get_results_chained_imputation(
        X_incomplete, y_scaled)
mice_coefs, mice_vars, mice_errorbar = get_results_mice_imputation(
        X_incomplete, y_scaled)
mice_y_coefs, mice_y_vars, mice_y_errorbar = \
    get_results_mice_imputation_includingy(
        X_incomplete, y_scaled)

# Combine the results from the four imputation procedures.
coefs = (full_coefs, chained_coefs, mice_coefs, mice_y_coefs)
vars = (full_vars, chained_vars, mice_vars, mice_y_vars)
errorbars = (full_errorbar, chained_errorbar, mice_errorbar, mice_y_errorbar)

# And plot the results
n_situations = 4
n = np.arange(n_situations)
n_labels = ['Full Data', 'IterativeImputer',
            'Mice Imputer', 'Mice Imputer with y']
colors = ['r', 'orange', 'b', 'purple']
width = 0.3
plt.figure(figsize=(24, 32))

plt1 = plt.subplot(211)
for j in n:
    plt1.bar(np.arange(len(coefs[j])) + (3*j*(width/n_situations)),
             coefs[j], width=width, color=colors[j])
plt.legend(n_labels)

plt2 = plt.subplot(212)
for j in n:
    plt2.bar(np.arange(len(errorbars[j])) + (3*j*(width/n_situations)),
             errorbars[j], width=width, color=colors[j])

plt1.set_title("MCAR Missingness")
plt1.set_ylabel("Beta Coefficients")
plt2.set_ylabel("Standard Errors")
plt1.set_xlabel("Features")
plt2.set_xlabel("Features")
plt.show()

###############################################################################

# EXAMPLE 2. SHOW MULTIPLE IMPUTATION IN A PREDICTION CONTEXT.

###############################################################################


# In this example, we show how to apply multiple imputation in a train/test
# situation. There are two approaches to get the end result of the prediction
# model. In approach 1 you calculate the evaluation metric for every i in m and
# later average these values. In approach 2 you average the predictions of
# every i in m and then calculate the evaluation metric. We test both
# approaches.
#
# Apply the regression model on the full dataset as a way of comparison.
def get_mse(X_train, X_test, y_train, y_test):
    # Standardize data
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Perform estimation and prediction
    estimator = RidgeCV()
    estimator.fit(X_train_scaled, y_train)
    y_predict = estimator.predict(X_test_scaled)

    return mse(y_test, y_predict), y_predict


# Use the IterativeImputer as a single imputation procedure.
def get_mse_single_imputation(X_train, X_test, y_train, y_test):
    # Apply imputation
    imputer = IterativeImputer(n_iter=N_ITER,
                               sample_posterior=True,
                               random_state=0)
    X_train_imputed = imputer.fit_transform(X_train)
    X_test_imputed = imputer.transform(X_test)

    mse_single, _ = get_mse(X_train_imputed, X_test_imputed, y_train, y_test)

    return mse_single


# We average the predictions of the m datasets.
def get_mse_multiple_imputation_approach(X_train, X_test, y_train, y_test):
    m = 5
    multiple_predictions = []
    for i in range(m):
        # Fit the imputer for every i in m
        # Be aware that you fit the imputer on the train data
        # And apply to the test data
        imputer = IterativeImputer(n_iter=N_ITER,
                                   sample_posterior=True,
                                   random_state=i)
        X_train_imputed = imputer.fit_transform(X_train)
        X_test_imputed = imputer.transform(X_test)

        _, y_predict = get_mse(
            X_train_imputed, X_test_imputed, y_train, y_test)
        multiple_predictions.append(y_predict)

    # Average the predictions over the m loops
    # Then calculate the error metric.
    predictions_average = np.mean(multiple_predictions, axis=0)
    mse_multiple = mse(y_test, predictions_average)

    return mse_multiple


def perform_simulation(dataset, X_incomplete, n_sim=10):
    X_full, y = dataset.data, dataset.target
    outcome = []

    # Start a simulation process that executes the process n_sim times.
    for j in np.arange(n_sim):
        # First, split the data in train and test dataset.
        train_indices, test_indices = train_test_split(
                np.arange(X_full.shape[0]), random_state=j)
        X_incomplete_train = X_incomplete[train_indices]
        X_full_train = X_full[train_indices]
        X_incomplete_test = X_incomplete[test_indices]
        X_full_test = X_full[test_indices]
        y_train = y[train_indices]
        y_test = y[test_indices]

        # Second, perform the imputation procedures and calculation of the
        # error metric for every one of the  situations.
        mse_full = get_mse(X_full_train, X_full_test, y_train, y_test)
        mse_single = get_mse_single_imputation(
                X_incomplete_train, X_incomplete_test, y_train, y_test)
        mse_multiple = get_mse_multiple_imputation_approach(
                X_incomplete_train, X_incomplete_test, y_train, y_test)

        # Save the outcome of every simulation round
        outcome.append((mse_full[0], mse_single, mse_multiple))

    # Return the mean and standard deviation of the n_sim outcome values
    return np.mean(outcome, axis=0), np.std(outcome, axis=0)


# Execute the simulation
print("Executing Example 2 MCAR Missingness...")

# Perform the simulation
mse_means, mse_std = perform_simulation(dataset, X_incomplete, n_sim=N_SIM)

# Plot results
n_situations = 3
n = np.arange(n_situations)
n_labels = ['Full Data', 'Single Imputation', 'Multiple Imputations']
colors = ['r', 'orange', 'green']

plt.figure(figsize=(24, 12))
ax1 = plt.subplot(111)
for j in n:
    ax1.barh(j, mse_means[j], xerr=mse_std[j],
             color=colors[j], alpha=0.6, align='center')

ax1.set_title('MCAR Missingness')
ax1.set_yticks(n)
ax1.set_xlabel('Mean Squared Error')
ax1.invert_yaxis()
ax1.set_yticklabels(n_labels)
plt.show()
