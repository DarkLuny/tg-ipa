#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@class PluginInvocation;

PluginInvocation *PluginInvocationFromObject(id object);

/// Swift-visible wrapper around NSInvocation.
///
/// `NSInvocation` is marked unavailable in Swift on iOS, but the Objective-C
/// runtime still hands one to `forwardInvocation:`. This class keeps the
/// unavailable type on the Objective-C side and exposes only Foundation types
/// to Swift.
@interface PluginInvocation : NSObject

@property (nonatomic, readonly) SEL selector;
@property (nonatomic, readonly) NSMethodSignature *methodSignature;
@property (nonatomic, readonly) id rawInvocation;

+ (instancetype)invocationWithObject:(id)object;

- (instancetype)initWithInvocation:(NSInvocation *)invocation NS_DESIGNATED_INITIALIZER;
- (instancetype)init NS_UNAVAILABLE;

- (void)getArgument:(void *)buffer atIndex:(NSInteger)index;
- (void)setArgument:(void *)buffer atIndex:(NSInteger)index;
- (void)setReturnValue:(void *)buffer;
- (void)getReturnValue:(void *)buffer;
- (void)invoke;

@end

NS_ASSUME_NONNULL_END
