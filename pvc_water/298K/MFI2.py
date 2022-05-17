import glob
import matplotlib.pyplot as plt
#from numba import jit 
#from numba import njit
import numpy as np
import scipy.sparse as sps
import scipy.sparse.linalg as spsl


### Load files ####
def load_HILLS_2D(hills_name = "HILLS"):
    """_summary_
    Args:
        hills_name (str, optional): _description_. Defaults to "HILLS".
    Returns:
        _type_: _description_
    """
    for file in glob.glob(hills_name):
        hills = np.loadtxt(file)
        hills = np.concatenate(([hills[0]], hills[:-1]))
        hills[0][5] = 0
    return hills

def load_position_2D(position_name = "position"):
    for file1 in glob.glob(position_name):
        colvar = np.loadtxt(file1)
        position_x = colvar[:-1, 1]
        position_y = colvar[:-1, 2]
    return [position_x, position_y]
#######

### Periodic CVs utils
#@jit
def find_periodic_point(x_coord,y_coord,min_grid,max_grid,periodic):
    """_summary_
    Args:
        x_coord (_type_): _description_
        y_coord (_type_): _description_
        min_grid (_type_): _description_
        max_grid (_type_): _description_
        periodic (_type_): _description_
    Returns:
        _type_: _description_
    """
    
    #Use periodic extension for defining PBC
    periodic_extension = periodic * 1 / 2
    grid_ext = (1/2) * periodic_extension * (max_grid-min_grid)
    
    coord_list = []
    #There are potentially 4 points, 1 original and 3 periodic copies
    coord_list.append([x_coord,y_coord])
    copy_record = [0,0,0,0]
    #check for x-copy
    if x_coord < min_grid[0]+grid_ext[0]:
        coord_list.append([x_coord + 2*np.pi,y_coord])
        copy_record[0] = 1
    elif x_coord > max_grid[0]-grid_ext[0]:
        coord_list.append([x_coord - 2*np.pi,y_coord])
        copy_record[1] = 1
    #check for y-copy
    if y_coord < min_grid[1]+grid_ext[1]:
        coord_list.append([x_coord, y_coord + 2 * np.pi])
        copy_record[2] = 1
    elif y_coord > max_grid[1]-grid_ext[1]:
        coord_list.append([x_coord, y_coord - 2 * np.pi])
        copy_record[3] = 1
    #check for xy-copy
    if sum(copy_record) == 2:
        if copy_record[0] == 1 and copy_record[2] == 1: coord_list.append([x_coord + 2 * np.pi, y_coord + 2 * np.pi])
        elif copy_record[1] == 1 and copy_record[2] == 1: coord_list.append([x_coord - 2 * np.pi, y_coord + 2 * np.pi])
        elif copy_record[0] == 1 and copy_record[3] == 1: coord_list.append([x_coord + 2 * np.pi, y_coord - 2 * np.pi])
        elif copy_record[1] == 1 and copy_record[3] == 1: coord_list.append([x_coord - 2 * np.pi, y_coord - 2 * np.pi])

    return coord_list

### Main Mean Force Integration
#@jit
def MFI_2D( HILLS = "HILLS",\
     position_x = "position_x", position_y = "position_y",\
     bw = 1, kT = 1, min_grid=np.array((-np.pi, -np.pi)),\
     max_grid=np.array((np.pi, np.pi)),\
     nbins = np.array((200,200)),\
     log_pace = 10, error_pace = 200,\
     WellTempered = 1, nhills = -1, periodic=0): 
    """Compute a time-independent estimate of the Mean Thermodynamic Force, i.e. the free energy gradient in 2D CV spaces. 
    Args:
        HILLS (str, optional): HILLS array. Defaults to "HILLS".
        position_x (str, optional): CV1 array. Defaults to "position_x".
        position_y (str, optional): CV2 array. Defaults to "position_y".
        bw (int, optional): Scalar, bandwidth for the construction of the KDE estimate of the biased probability density. Defaults to 1.
        kT (int, optional): Scalar, kT. Defaults to 1.
        min_grid (_type_, optional): Lower bound of the simulation domain. Defaults to np.array((-np.pi, -np.pi)).
        max_grid (_type_, optional): Upper bound of the simulation domain. Defaults to np.array((np.pi, np.pi)).
        nbins (int, optional): number of bins in CV1,CV2. Defaults to np.array((200,200)).
        log_pace (int, optional): Pace for outputting progress and convergence. Defaults to 10.
        error_pace (int, optional): Pace for the calculation of the on-the-fly measure of global convergence. Defaults to 200.
        WellTempered (int, optional): Is the simulation well tempered? . Defaults to 1.
        nhills (int, optional): Number of HILLS to analyse, -1 for the entire HILLS array. Defaults to -1, i.e. the entire dataset.
        periodic (int, optional): Is the CV space periodic? 1 for yes. Defaults to 0. 
    Returns:
        X: array of size (nbins[0], nbins[1]) - CV1 grid positions
        Y: array of size (nbins[0], nbins[1]) - CV2 grid positions
        Ftot_den: array of size (nbins[0], nbins[1]) - Cumulative biased probability density, equivalent to an unbiased histogram of samples in CV space. 
        Ftot_x:  array of size (nbins[0], nbins[1]) - CV1 component of the Mean Force. 
        Ftot_y:  array of size (nbins[0], nbins[1]) - CV2 component of the Mean Force. 
        ofe:  array of size (nbins[0], nbins[1]) - on the fly estimate of the local convergence
        ofe_history: array of size (1, total_number_of_hills) - running estimate of the global convergence of the mean force.
    """

    gridx = np.linspace(min_grid[0], max_grid[0], nbins[0])
    gridy = np.linspace(min_grid[1], max_grid[1], nbins[1])
    X, Y = np.meshgrid(gridx, gridy)
    stride = int(len(position_x) / len(HILLS[:,1]))     
    const = (1 / (bw*np.sqrt(2*np.pi)*stride))

    if log_pace >= error_pace:
        log_pace=error_pace 
    
    # Optional - analyse only nhills, if nhills is set
    if  nhills > 0: 
        total_number_of_hills=nhills
    else:
        total_number_of_hills=len(HILLS[:,1])
    bw2 = bw**2    

    # Initialize force terms
    Fbias_x = np.zeros(nbins)
    Fbias_y = np.zeros(nbins)
    Ftot_num_x = np.zeros(nbins)
    Ftot_num_y = np.zeros(nbins)
    Ftot_den = np.zeros(nbins)
    Ftot_den2 = np.zeros(nbins)
    ofv_x = np.zeros(nbins)
    ofv_y = np.zeros(nbins)
    ofe_history = []

    print("Total no. of Gaussians analysed: " + str(total_number_of_hills))

    # Definition Gamma Factor, allows to switch between WT and regular MetaD
    if WellTempered < 1: 
        Gamma_Factor=1
    else:
        gamma = HILLS[0, 6]
        Gamma_Factor=(gamma - 1)/(gamma)
      
        
    for i in range(total_number_of_hills):
        # Build metadynamics potential
        s_x = HILLS[i, 1]  # center x-position of Gaussian
        s_y = HILLS[i, 2]  # center y-position of Gaussian
        sigma_meta2_x = HILLS[i, 3] ** 2  # width of Gaussian
        sigma_meta2_y = HILLS[i, 4] ** 2  # width of Gaussian
        height_meta = HILLS[i, 5] * Gamma_Factor  # Height of Gaussian

        periodic_images = find_periodic_point(s_x,s_y,min_grid,max_grid,periodic)
        for j in range(len(periodic_images)):
            kernelmeta = np.exp(-0.5 * (((X - periodic_images[j][0]) ** 2) / sigma_meta2_x + ((Y - periodic_images[j][1]) ** 2) / sigma_meta2_y))  # potential erorr in calc. of s-s_t
            Fbias_x = Fbias_x + height_meta * kernelmeta * ((X - periodic_images[j][0]) / sigma_meta2_x);  
            Fbias_y = Fbias_y + height_meta * kernelmeta * ((Y - periodic_images[j][1]) / sigma_meta2_y);  

        # Biased probability density component of the force
        # Estimate the biased proabability density p_t ^ b(s)
        pb_t = np.zeros(nbins)
        Fpbt_x = np.zeros(nbins)
        Fpbt_y = np.zeros(nbins)

        data_x = position_x[i * stride: (i + 1) * stride]
        data_y = position_y[i * stride: (i + 1) * stride]

        for j in range(stride):
            periodic_images = find_periodic_point(data_x[j], data_y[j], min_grid, max_grid,periodic)
            for k in range(len(periodic_images)):
                kernel = const * np.exp(- (1 / (2 * bw2)) * ((X - periodic_images[k][0]) ** 2 + (Y - periodic_images[k][1]) ** 2)); 
                pb_t = pb_t + kernel;
                Fpbt_x = Fpbt_x + kernel * kT * (X - periodic_images[k][0]) / bw2
                Fpbt_y = Fpbt_y + kernel * kT * (Y - periodic_images[k][1]) / bw2
            
        # Calculate Mean Force
        Ftot_den = Ftot_den + pb_t;
        # Calculate x-component of Force
        dfds_x = np.divide(Fpbt_x, pb_t, out=np.zeros_like(Fpbt_x), where=pb_t != 0) + Fbias_x 
        Ftot_num_x = Ftot_num_x + pb_t * dfds_x
        Ftot_x = np.divide(Ftot_num_x, Ftot_den, out=np.zeros_like(Fpbt_x), where=Ftot_den != 0)
        # Calculate y-component of Force
        dfds_y = np.divide(Fpbt_y, pb_t, out=np.zeros_like(Fpbt_y), where=pb_t != 0) + Fbias_y 
        Ftot_num_y = Ftot_num_y + pb_t * dfds_y
        Ftot_y = np.divide(Ftot_num_y, Ftot_den, out=np.zeros_like(Fpbt_y), where=Ftot_den != 0)

        #calculate on the fly error components
        Ftot_den2 = Ftot_den2 + pb_t**2   
        # on the fly variance of the mean force
        ofv_x += pb_t * dfds_x**2
        ofv_y += pb_t * dfds_y**2

        # Compute Variance of the mean force every 1/error_pace frequency
        if (i + 1) % int(total_number_of_hills / error_pace) == 0:       
            #calculate ofe (standard error)
            [ofe] = mean_force_variance(Ftot_den,Ftot_den2,Ftot_x,Ftot_y,ofv_x,ofv_y)
                   
            ofe_history.append(sum(sum(ofe)) / (nbins[0]*nbins[1]))

        if (i+1) % (total_number_of_hills/log_pace) == 0: 
            print("|"+ str(i+1) + "/" + str(total_number_of_hills)+"|==> Average Mean Force Error: "+str(sum(sum(ofe)) / (nbins[0]*nbins[1])))
            
    return [X, Y, Ftot_den, Ftot_x, Ftot_y, ofe, ofe_history, Ftot_den2, ofv_x, ofv_y]


#@jit
def mean_force_variance(Ftot_den,Ftot_den2,Ftot_x,Ftot_y,ofv_x,ofv_y): 
   #calculate ofe (standard error)
    Ftot_den_ratio = np.divide(Ftot_den2, (Ftot_den**2 - Ftot_den2), out=np.zeros_like(Ftot_den), where=(Ftot_den**2 - Ftot_den2) != 0)
    ofe_x = np.divide(ofv_x, Ftot_den, out=np.zeros_like(ofv_x), where=Ftot_den != 0) - Ftot_x**2
    ofe_y = np.divide(ofv_y, Ftot_den, out=np.zeros_like(ofv_y), where=Ftot_den != 0) - Ftot_y**2       
    ofe_x = ofe_x * Ftot_den_ratio
    ofe_y = ofe_y * Ftot_den_ratio
    ofe = np.sqrt(abs(ofe_x) + abs(ofe_y))                
    return [ofe]
  




### Integration using Fast Fourier Transform (FFT integration) in 2D            
def FFT_intg_2D(FX, FY, min_grid=np.array((-np.pi, -np.pi)), max_grid=np.array((np.pi, np.pi)), nbins = np.array((200,200))):   
    
    gridx = np.linspace(min_grid[0], max_grid[0], nbins[0])
    gridy = np.linspace(min_grid[1], max_grid[1], nbins[1])
    grid_spacex = (max_grid[0] - min_grid[0]) / (nbins[0] - 1)
    grid_spacey = (max_grid[1] - min_grid[1]) / (nbins[1] - 1)
    X, Y = np.meshgrid(gridx, gridy)

    #Calculate frequency
    freq_1dx = np.fft.fftfreq(nbins[0], grid_spacex)
    freq_1dy = np.fft.fftfreq(nbins[1], grid_spacey)
    freq_x, freq_y = np.meshgrid(freq_1dx, freq_1dy)
    freq_hypot = np.hypot(freq_x, freq_y)
    freq_sq = np.where(freq_hypot != 0, freq_hypot ** 2, 1E-10)
    #FFTransform and integration
    fourier_x = (np.fft.fft2(FX) * freq_x) / (2 * np.pi * 1j * freq_sq)
    fourier_y = (np.fft.fft2(FY) * freq_y) / (2 * np.pi * 1j * freq_sq)
    #Reverse FFT
    fes_x = np.real(np.fft.ifft2(fourier_x))
    fes_y = np.real(np.fft.ifft2(fourier_y))
    #Construct whole FES
    fes = fes_x + fes_y
    fes = fes - np.min(fes)
    return [X, Y, fes]

#Equivalent to integration MS in Alanine dipeptide notebook.     
def intg_2D(FX, FY, min_grid=np.array((-np.pi, -np.pi)), max_grid=np.array((np.pi, np.pi)), nbins = np.array((200,200))): 
    """_summary_
    Args:
        FX (_type_): _description_
        FY (_type_): _description_
        min_grid (_type_, optional): _description_. Defaults to np.array((-np.pi, -np.pi)).
        max_grid (_type_, optional): _description_. Defaults to np.array((np.pi, np.pi)).
        nbins (_type_, optional): _description_. Defaults to np.array((200,200)).
    Returns:
        _type_: _description_
    """
    
    gridx = np.linspace(min_grid[0], max_grid[0], nbins[0])
    gridy = np.linspace(min_grid[1], max_grid[1], nbins[1])
    X, Y = np.meshgrid(gridx, gridy)

    FdSx = np.cumsum(FX, axis=1)*np.diff(gridx)[0]
    FdSy = np.cumsum(FY, axis=0)*np.diff(gridy)[0]

    fes = np.zeros(FdSx.shape)
    for i in range(fes.shape[0]):
        for j in range(fes.shape[1]):
            fes[i,j] += np.sum([FdSy[i,0], -FdSy[0,0], FdSx[i,j], -FdSx[i,0]])

    fes = fes - np.min(fes)

    return [X, Y, fes]

#@jit(nopython=True)
def intgrad2(fx,fy,nx,ny,dx,dy,intconst,per1,per2,min_grid,max_grid,nbins):

    '''

    This function uses the inverse of the gradient to reconstruct the free energy surface from the mean force components.

    [John D'Errico (2022). Inverse (integrated) gradient (https://www.mathworks.com/matlabcentral/fileexchange/9734-inverse-integrated-gradient), MATLAB Central File Exchange. Retrieved May 17, 2022.]

    '''
	
    gridx = np.linspace(min_grid[0], max_grid[0], nbins[0])
    gridy = np.linspace(min_grid[1], max_grid[1], nbins[1])
    X, Y = np.meshgrid(gridx, gridy)

    rhs = np.ravel((fx,fy))
    
    Af=np.zeros((4*nx*ny,3))
    
    n=0
    #Equations in x
    for i in range(0,ny):
    	#Leading edge
    	Af[2*nx*i][0] = 2*nx*i/2
    	if(per2):
    		Af[2*nx*i][1] = nx*i+(nx-1)
    	else:
    		Af[2*nx*i][1] = nx*i
    	Af[2*nx*i][2] = -0.5/dx
    
    	Af[2*nx*i+1][0] = 2*nx*i/2
    	Af[2*nx*i+1][1] = nx*i+1
    	Af[2*nx*i+1][2] = 0.5/dx
    
    	#Loop over inner space
    	for j in range(1,nx-1):
    		Af[2*nx*i+2*j][0] = int((2*nx*i+2*j)/2)
    		Af[2*nx*i+2*j][1] = nx*i+j
    		Af[2*nx*i+2*j][2] = -1/dx
    
    		Af[2*nx*i+2*j+1][0] = int((2*nx*i+2*j)/2)
    		Af[2*nx*i+2*j+1][1] = nx*i+j+1
    		Af[2*nx*i+2*j+1][2] = 1/dx
    
    	#Trailing edge
    	Af[2*nx*(i+1)-2][0] = int((2*nx*(i+1)-2)/2)
    	Af[2*nx*(i+1)-2][1] = nx*i+(nx-2)
    	Af[2*nx*(i+1)-2][2] = -0.5/dx
    
    	Af[2*nx*(i+1)-1][0] = int((2*nx*(i+1)-2)/2)
    	if(per2):
    		Af[2*nx*(i+1)-1][1] = nx*i
    	else:
    		Af[2*nx*(i+1)-1][1] = nx*i+(nx-1)
    	Af[2*nx*(i+1)-1][2] = 0.5/dx
    
    
    n=2*nx*ny
    
    #Equations in y
    #Leading edge
    for j in range(0,nx):
    
    	Af[2*j+n][0] = 2*j/2 + n/2
    	
    	if(per1):
    		Af[2*j+n][1] = (ny-1)*nx+j
    	else:
    		Af[2*j+n][1] = j
    	Af[2*j+n][2] = -0.5/dy
    
    	Af[2*j+n+1][0] = 2*j/2 + n/2
    	Af[2*j+n+1][1] = j+nx
    	Af[2*j+n+1][2] = 0.5/dy
    
    #Loop over inner space
    for i in range(1,ny-1):
    	for j in range(0,nx):
    		
    		Af[2*nx*i+2*j+n][0] = int((2*nx*i+2*j+n)/2)
    		Af[2*nx*i+2*j+n][1] = j+(i)*nx
    		Af[2*nx*i+2*j+n][2] = -1/dy
    
    		Af[2*nx*i+2*j+n+1][0] = int((2*nx*i+2*j+n)/2)
    		Af[2*nx*i+2*j+n+1][1] = j+(i+1)*nx
    		Af[2*nx*i+2*j+n+1][2] = 1/dy
    		a=2*nx*i+2*j+n+1
    n=n+2*(ny-1)*nx
    
    #Trailing edge
    for j in range(0,nx):
    	Af[2*j+n][0] = int((2*j+n)/2)
    	Af[2*j+n][1] = (ny-2)*nx+j
    	Af[2*j+n][2] = -0.5/dy
    
    	Af[2*j+n+1][0] = int((2*j+n)/2)
    	if(per1):
    		Af[2*j+n+1][1] = j
    	else:
    		Af[2*j+n+1][1] = (ny-1)*nx+j
    	Af[2*j+n+1][2] = 0.5/dy
    
    
    #Boundary conditions
    Af[0][2]=1
    Af[1][:]=0
    rhs[0] = intconst
    
    #Solve
    A=sps.csc_matrix((Af[:,2],(Af[:,0],Af[:,1])),shape=(2*ny*nx,ny*nx))
    fhat=spsl.lsmr(A,rhs)
    fhat=fhat[0]
    fhat = np.reshape(fhat,nbins) 
    #print(fhat.shape)   
    fhat = fhat - np.min(fhat)

    return [X, Y, fhat]


def plot_recap_2D(X, Y, FES, TOTAL_DENSITY, CONVMAP, CONV_history,FES_lim=120,ofe_map_lim=40): 
    """_summary_
    Args:
        X (_type_): _description_
        Y (_type_): _description_
        FES (_type_): _description_
        TOTAL_DENSITY (_type_): _description_
        CONVMAP (_type_): _description_
        CONV_history (_type_): _description_
    """
    fig, axs = plt.subplots(1,4,figsize=(18,3))
    cp=axs[0].contourf(X,Y,FES,levels=range(0,FES_lim,1),cmap='YlGnBu_r',antialiased=False,alpha=0.8);
    cbar = plt.colorbar(cp, ax=axs[0])
    axs[0].set_ylabel('CV2',fontsize=11)
    axs[0].set_xlabel('CV1',fontsize=11)
    axs[0].set_title('Free Energy Surface',fontsize=11)
    
    cp=axs[1].contourf(X,Y,CONVMAP,levels=range(0,ofe_map_lim,1),cmap='YlGnBu_r',antialiased=False,alpha=0.8);
    cbar = plt.colorbar(cp, ax=axs[1])
    axs[1].set_ylabel('CV2',fontsize=11)
    axs[1].set_xlabel('CV1',fontsize=11)
    axs[1].set_title('Variance of the Mean Force',fontsize=11)

    cp=axs[2].contourf(X,Y,TOTAL_DENSITY,cmap='gray_r',antialiased=False,alpha=0.8);
    cbar = plt.colorbar(cp, ax=axs[2])
    axs[2].set_ylabel('CV2',fontsize=11)
    axs[2].set_xlabel('CV1',fontsize=11)
    axs[2].set_title('Total Biased Probability Density',fontsize=11)

    axs[3].plot(range(len(CONV_history)), CONV_history);
    axs[3].set_ylabel('Average Mean Force Error',fontsize=11)
    axs[3].set_xlabel('Number of Error Evaluations',fontsize=11)
    axs[3].set_title('Global Convergence',fontsize=11)

    plt.show()

# Patch independent simulations
#@jit
def patch_2D(master_array,nbins = np.array((200,200))):

    FX = np.zeros(nbins)
    FY = np.zeros(nbins)
    FP = np.zeros(nbins)

    for i in range(len(master_array)):
        FX += master_array[i][0] * master_array[i][1]
        FY += master_array[i][0] * master_array[i][2]
        FP += master_array[i][0]

    FX = np.divide(FX, FP, out=np.zeros_like(FX), where=FP != 0)
    FY = np.divide(FY, FP, out=np.zeros_like(FY), where=FP != 0)
    
    return [FP, FX, FY]

def plot_patch_2D(X, Y, FES, TOTAL_DENSITY,lim=50): 
    """_summary_
    Args:
        X (_type_): _description_
        Y (_type_): _description_
        FES (_type_): _description_
        TOTAL_DENSITY (_type_): _description_
        CONVMAP (_type_): _description_
        CONV_history (_type_): _description_
    """
    fig, axs = plt.subplots(1,2,figsize=(9,3.5))
    cp=axs[0].contourf(X,Y,FES,levels=range(0,lim,1),cmap='YlGnBu_r',antialiased=False,alpha=0.8);
    cbar = plt.colorbar(cp, ax=axs[0])
    axs[0].set_ylabel('CV2',fontsize=11)
    axs[0].set_xlabel('CV1',fontsize=11)
    axs[0].set_title('Free Energy Surface',fontsize=11)

    cp=axs[1].contourf(X,Y,TOTAL_DENSITY,cmap='gray_r',antialiased=False,alpha=0.8);
    cbar = plt.colorbar(cp, ax=axs[1])
    axs[1].set_ylabel('CV2',fontsize=11)
    axs[1].set_xlabel('CV1',fontsize=11)
    axs[1].set_title('Total Biased Probability Density',fontsize=11)


#@jit
def patch_2D_error(master,nbins = np.array((200,200))):

       
    Ftot_x = np.zeros(nbins)
    Ftot_y = np.zeros(nbins)
    Ftot_den = np.zeros(nbins)
    Ftot_den2 = np.zeros(nbins)
    ofv_x = np.zeros(nbins)
    ofv_y = np.zeros(nbins)
    error_x = np.zeros(nbins)
    error_y = np.zeros(nbins)
    
    for i in np.arange(0,len(master)):
        Ftot_x += master[i][0] * master[i][2]
        Ftot_y += master[i][0] * master[i][3]
        Ftot_den += master[i][0]
        Ftot_den2 += master[i][1]
        ofv_x += master[i][4]
        ofv_y += master[i][5]
        error_x += master[i][0] * (master[i][2]**2)
        error_y += master[i][0] * (master[i][3]**2)

    Ftot_x = np.divide(Ftot_x, Ftot_den, out=np.zeros_like(Ftot_x), where=Ftot_den != 0)
    Ftot_y = np.divide(Ftot_y, Ftot_den, out=np.zeros_like(Ftot_y), where=Ftot_den != 0)
        
              
    error_x = np.divide(error_x, Ftot_den, out=np.zeros_like(error_x), where=Ftot_den != 0) - (Ftot_x**2)
    error_y = np.divide(error_y, Ftot_den, out=np.zeros_like(error_y), where=Ftot_den != 0) - (Ftot_y**2)
       
    ratio = np.divide(Ftot_den2, (Ftot_den**2 - Ftot_den2), out=np.zeros_like(error_x), where=(Ftot_den**2 - Ftot_den2) != 0)
    error_x = error_x * ratio
    error_y = error_y * ratio
        
    error = np.sqrt(np.sqrt(error_x**2 + error_y**2))

    return [Ftot_x,Ftot_y,Ftot_den,error]

