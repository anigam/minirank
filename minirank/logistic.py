"""
Implementation of logistic ordinal regression (aka proportional odds) model
"""

from __future__ import print_function

from sklearn import utils, metrics
from scipy import linalg, optimize, sparse
import numpy as np

BIG = 1e10


def phi(t):
    # logistic function
    idx = t > 0
    out = np.empty(t.size, dtype=np.float)
    out[idx] = 1. / (1 + np.exp(-t[idx]))
    exp_t = np.exp(t[~idx])
    out[~idx] = exp_t / (1. + exp_t)
    return out

def log_logistic(t):
    # logistic loss function
    idx = t > 0
    out = np.zeros_like(t)
    out[idx] = np.log(1 + np.exp(-t[idx]))
    out[~idx] = (-t[~idx] + np.log(1 + np.exp(t[~idx])))
    out = out.sum()
    return out


def ordinal_logistic_fit(X, y, max_iter=10000, verbose=False):
    """
    Ordinal logistic regression or proportional odds model.
    Uses scipy's optimize.fmin_slsqp solver.

    Parameters
    ----------
    X : {array, sparse matrix}, shape (n_samples, n_feaures)
        Input data
    y : array-like
        Target values
    max_iter : int
        Maximum number of iterations
    verbose: bool
        Print convergence information

    Returns
    -------
    w : array, shape (n_features,)
        coefficients of the linear model
    theta : array, shape (k,), where k is the different values of y
        vector of thresholds
    """

    X = utils.safe_asarray(X)
    y = np.asarray(y)

    # .. order input ..
    idx = np.argsort(y)
    idx_inv = np.zeros_like(idx)
    idx_inv[idx] = np.arange(idx.size)
    X = X[idx]
    y = y[idx].astype(np.int)
    # make them continuous and start at zero
    unique_y = np.unique(y)
    for i, u in enumerate(unique_y):
        y[y == u] = i
    unique_y = np.unique(y)

    # .. utility arrays used in f_grad ..
    L_inv = np.tril(np.ones((unique_y.size, unique_y.size)))
    alpha = 0.


    def f_obj(x0, X, y):
        """
        Objective function
        """
        w, z = np.split(x0, [X.shape[1]])
        theta0 = L_inv.dot(z)
        theta1 = np.roll(theta0, 1)  # theta_{y_i - 1}

        Xw = X.dot(w)
        a = theta0[y] - Xw
        b = theta1[y] - Xw
        a0 = phi(a)
        b0 = phi(b)
        b0[y == 0] = 0.
        out = - np.log(phi(a0) - phi(b0))

        tmp = np.fmax(z[1:], 1e-6)
        return out.sum() + .5 * alpha * w.dot(w) - np.log(tmp).sum()


    def f_grad(x0, X, y):
        """
        Gradient of the objective function
        """
        w, z = np.split(x0, [X.shape[1]])
        theta0 = L_inv.dot(z)
        theta1 = np.roll(theta0, 1)  # theta_{y_i - 1}
        theta1[0] = - np.inf
        Xw = X.dot(w)
        a = theta0[y] - Xw
        b = theta1[y] - Xw

        # gradient for w
        a0 = phi(a)
        b0 = phi(b)
        b0[y == 0] = 0.
        grad_w = X.T.dot((a0 * (1 - a0) - b0 * (1 - b0)) / (a0 - b0)) + alpha * w

        L1_inv = np.roll(L_inv, 1, axis=0)
        grad_z = -L_inv[y].T.dot((a0 * (1 - a0) / (a0 - b0)))

        idx = y > 0
        y0 = y[idx]
        b0 = b0[idx]
        import ipdb; ipdb.set_trace()
        grad_z += L1_inv[y0].T.dot(b0 * (1 - b0) / (a0[idx] - b0))
        grad_z[1:] -= 1. / np.fmax(z[1:], 1e-6)
        out = np.concatenate((grad_w, grad_z))
        return out


    #x0 = np.random.randn(X.shape[1] + unique_y.size) / X.shape[1]
    x0 = np.zeros(X.shape[1] + unique_y.size) / X.shape[1]
    x0[X.shape[1]] = -.5
    x0[X.shape[1] + 1:] = 2. / unique_y.size

    print(optimize.check_grad(f_obj, f_grad, x0, X, y))
    import ipdb; ipdb.set_trace()

    def callback(x0):
        # check that gradient is correctly computed
        print(f_obj(x0, X, y))

    bounds = [(None, None)] * (X.shape[1] + 1) + [(1. / unique_y.size, None)] * (unique_y.size - 1)
    options = {'maxiter' : max_iter, 'disp': 0, }
    out = optimize.minimize(f_obj, x0, args=(X, y), method='TNC', jac=f_grad,
                           options=options, callback=callback)

    assert out.success
    w, z = np.split(out.x, [X.shape[1]])
    theta = L_inv.dot(z)
    #import ipdb; ipdb.set_trace()
    return w, theta[y][idx_inv]


def ordinal_logistic_predict(w, theta, X, y):
    """
    Parameters
    ----------
    w : coefficients obtained by ordinal_logistic
    theta : thresholds
    """
    unique_y = np.sort(np.unique(y))
    unique_theta = np.unique(theta)
    mu = [-1]
    for i in range(unique_theta.size - 1):
        mu.append((unique_theta[i] + unique_theta[i+1]) / 2.)
        # todo: use roll
    out = X.dot(w)
    mu = np.array(mu)
    tmp = metrics.pairwise.pairwise_distances(out[:, None], mu[:, None])
    return unique_y[np.argmin(tmp, 1)]

if __name__ == '__main__':
    DOC = """
================================================================================
    Compare the prediction accuracy of different models on the boston dataset
================================================================================
    """
    print(DOC)
    from sklearn import cross_validation, datasets
    boston = datasets.load_boston()
    X, y = boston.data, np.round(boston.target)
    #X -= X.mean()
    y -= y.min()

    idx = np.argsort(y)
    X = X[idx]
    y = y[idx]
    cv = cross_validation.ShuffleSplit(y.size, n_iter=50, test_size=.1, random_state=0)
    score_logistic = []
    score_ordinal_logistic = []
    score_ridge = []
    for i, (train, test) in enumerate(cv):
        #test = train
        if not np.all(np.unique(y[train]) == np.unique(y)):
            # we need the train set to have all different classes
            continue
        assert np.all(np.unique(y[train]) == np.unique(y))
        train = np.sort(train)
        test = np.sort(test)
        w, theta = ordinal_logistic_fit(X[train], y[train])
        pred = ordinal_logistic_predict(w, theta, X[test], y)
        s = metrics.mean_absolute_error(y[test], pred)
        print('ERROR (ORDINAL)  fold %s: %s' % (i+1, s))
        score_ordinal_logistic.append(s)

        from sklearn import linear_model
        clf = linear_model.LogisticRegression(C=1.)
        clf.fit(X[train], y[train])
        pred = clf.predict(X[test])
        s = metrics.mean_absolute_error(y[test], pred)
        print('ERROR (LOGISTIC) fold %s: %s' % (i+1, s))
        score_logistic.append(s)

        from sklearn import linear_model
        clf = linear_model.Ridge(alpha=1.)
        clf.fit(X[train], y[train])
        pred = np.round(clf.predict(X[test]))
        s = metrics.mean_absolute_error(y[test], pred)
        print('ERROR (RIDGE)    fold %s: %s' % (i+1, s))
        score_ridge.append(s)


    print()
    print('MEAN ABSOLUTE ERROR (ORDINAL LOGISTIC):    %s' % np.mean(score_ordinal_logistic))
    print('MEAN ABSOLUTE ERROR (LOGISTIC REGRESSION): %s' % np.mean(score_logistic))
    print('MEAN ABSOLUTE ERROR (RIDGE REGRESSION):    %s' % np.mean(score_ridge))
    # print('Chance level is at %s' % (1. / np.unique(y).size))