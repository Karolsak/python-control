'''
Author: Mark Yeatman  
Date: May 15, 2022
'''

from msilib.schema import Error
import numpy as np
from control import statesp as ss

try:
    import cvxopt as cvx
except ImportError as e:
    cvx = None


def __parse_lti__(sys):
    '''
    Utility function to parse LTI input for passivity module functions
    '''
    sys = ss._convert_to_statespace(sys)

    A = sys.A
    B = sys.B
    C = sys.C
    D = sys.D

    # account for strictly proper systems
    [n, m] = D.shape
    D = D + np.nextafter(0, 1)*np.eye(n, m)

    [n, _] = A.shape
    A = A - np.nextafter(0, 1)*np.eye(n)

    return (A, B, C, D)


def __make_P_basis_matrices__(n, make_LMI_matrix_func):
    '''
    Utility function to make basis matrices for a LMI from a 
    functional make_LMI_matrix_func and a symmetric matrix P of size n by n
    representing a parametrized symbolic matrix
    '''
    matrix_list = []
    for i in range(0, n):
        for j in range(0, n):
            if j <= i:
                P = np.zeros((n, n))
                P[i, j] = 1.0
                P[j, i] = 1.0
                matrix_list.append(make_LMI_matrix_func(P).flatten())
    return matrix_list


def __P_pos_def_constraint__(n):
    '''
    Utility function to make basis matrices for a LMI that ensures parametrized symbolic matrix 
    of size n by n is positive definite.
    '''
    matrix_list = []
    for i in range(0, n):
        for j in range(0, n):
            if j <= i:
                P = np.zeros((n, n))
                P[i, j] = -1.0
                P[j, i] = -1.0
                matrix_list.append(P.flatten())
    return matrix_list


def ispassive(sys, nu=None, rho=None):
    '''
    Indicates if a linear time invariant (LTI) system is passive

    Constructs a linear matrix inequality and a feasibility optimization
    such that if a solution exists, the system is passive.

    The sources for the algorithm are: 

    McCourt, Michael J., and Panos J. Antsaklis
        "Demonstrating passivity and dissipativity using computational methods." 

    Nicholas Kottenstette and Panos J. Antsaklis
        "Relationships Between Positive Real, Passive Dissipative, & Positive Systems" 
        equation 36.

    Parameters
    ----------
    sys: An LTI system
        System to be checked.
    nu: float
        Concrete value for input passivity index. 
    rho: float
        Concrete value for output passivity index. 

    Returns
    -------
    bool or float: 
        The input system passive, or the passivity index "opposite" the input. 
    '''
    if cvx is None:
        raise ModuleNotFoundError("cvxopt required for passivity module")

    if not sys.isctime() and rho is not None and nu is not None:
        raise Exception(
            "Passivity indices for discrete time systems not supported yet.")

    if sys.ninputs != sys.noutputs:
        raise Exception(
            "The number of system inputs must be the same as the number of system outputs.")

    (A, B, C, D) = __parse_lti__(sys)

    def make_LMI_matrix(P):
        if sys.isctime():
            return np.vstack((
                np.hstack((A.T @ P + P@A, P@B)),
                np.hstack((B.T@P, np.zeros_like(D))))
            )
        else:
            return 2*np.vstack((
                np.hstack((A.T @ P @ A - P, A.T @ P@B)),
                np.hstack(((A.T @ P@B).T, B.T@P@B)))
            )

    n = sys.nstates

    # LMI for passivity from A,B,C,D
    sys_matrix_list = __make_P_basis_matrices__(n, make_LMI_matrix)

    sys_constants = -np.vstack((
        np.hstack((np.zeros_like(A),  - C.T)),
        np.hstack((- C, -D - D.T)))
    )

    if nu is not None:
        m = D.shape[1]
        sys_constants += -np.vstack((
            np.hstack((np.zeros_like(A),  np.zeros_like(C.T))),
            np.hstack((np.zeros_like(C),  nu*np.eye(m))))
        )

    if rho is not None:
        sys_constants += -np.vstack((
            np.hstack((rho*C.T@C,  rho*C.T@D)),
            np.hstack(((rho*C.T@D).T, rho*D.T@D)))
        )

    if rho is not None and nu is not None:
        sys_constants += -np.vstack((
            np.hstack((np.zeros_like(A),  -0.5*nu*rho*C.T)),
            np.hstack(((rho*C.T@D).T, rho*D.T@D)))
        )

    # LMI to ensure P is positive definite
    P_matrix_list = __P_pos_def_constraint__(n)

    number_of_opt_vars = int(
        (n**2-n)/2 + n)
    c = cvx.matrix(0.0, (number_of_opt_vars, 1))

    # LMI for passivity indices
    if nu is not None and rho is None:
        # pick out coefficents for rho
        rho_coefficents_matrix = np.vstack((
            np.hstack((C.T@C, 0.5*nu*C.T + C.T@D)),
            np.hstack(((0.5*nu*C.T + C.T@D).T, D.T@D-nu*(D+D.T))))
        )
        sys_matrix_list.append(rho_coefficents_matrix.flatten())
        c = cvx.matrix(np.append(np.array(c), -1.0))
        P_matrix_list.append(np.zeros_like(A).flatten())
    elif rho is not None and nu is None:
        # pick out coefficents for nu
        nu_coefficents_matrix = np.vstack((
            np.hstack((np.zeros_like(A), 0.5*rho*C.T)),
            np.hstack(((0.5*rho*C.T + rho*C.T@D).T, rho*D.T@D)))
        )
        sys_matrix_list.append(nu_coefficents_matrix.flatten())
        c = cvx.matrix(np.append(np.array(c), -1.0))
        P_matrix_list.append(np.zeros_like(A).flatten())

    sys_coefficents = np.vstack(sys_matrix_list).T
    P_coefficents = np.vstack(P_matrix_list).T
    P_constants = np.zeros((n, n))

    Gs = [cvx.matrix(sys_coefficents)] + [cvx.matrix(P_coefficents)]
    hs = [cvx.matrix(sys_constants)]+[cvx.matrix(P_constants)]

    # crunch feasibility solution
    cvx.solvers.options['show_progress'] = False
    sol = cvx.solvers.sdp(c, Gs=Gs, hs=hs)
    if nu is None and rho is None:
        return sol["x"] is not None
    else:
        return np.ravel(sol["x"])[-1]

def getPassiveIndex(sys, index_type = None):
    '''
    Returns the passivity index associated with the input string. 
    Parameters
    ----------
    sys: An LTI system
        System to be checked.
    index_type: String
        Must be 'input' or 'output'. Indicates which passivity index will be returned. 

    Returns
    -------
    float: 
        The passivity index 
    '''
    if index_type is None:
        raise Exception("Must provide index_type of 'input' or 'output'.")
    if index_type == "input":
        return ispassive(sys, rho = 0.000001)
    if index_type == "output":
        return ispassive(sys, nu = 0.000001)