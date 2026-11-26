#import "PluginInvocation.h"

@interface PluginInvocation () {
    NSInvocation *_invocation;
}
@end

PluginInvocation *PluginInvocationFromObject(id object) {
    return [PluginInvocation invocationWithObject:object];
}

@implementation PluginInvocation

+ (instancetype)invocationWithObject:(id)object {
    return [[[self alloc] initWithInvocation:(NSInvocation *)object] autorelease];
}

- (instancetype)initWithInvocation:(NSInvocation *)invocation {
    self = [super init];
    if (self) {
        _invocation = invocation;
    }
    return self;
}

- (SEL)selector {
    return _invocation.selector;
}

- (NSMethodSignature *)methodSignature {
    return _invocation.methodSignature;
}

- (id)rawInvocation {
    return _invocation;
}

- (void)getArgument:(void *)buffer atIndex:(NSInteger)index {
    [_invocation getArgument:buffer atIndex:index];
}

- (void)setArgument:(void *)buffer atIndex:(NSInteger)index {
    [_invocation setArgument:buffer atIndex:index];
}

- (void)setReturnValue:(void *)buffer {
    [_invocation setReturnValue:buffer];
}

- (void)getReturnValue:(void *)buffer {
    [_invocation getReturnValue:buffer];
}

- (void)invoke {
    [_invocation invoke];
}

@end
